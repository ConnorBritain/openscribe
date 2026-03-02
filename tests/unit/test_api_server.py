#!/usr/bin/env python3
"""
Test Local API Server
Validates the local HTTP server endpoints, application state transitions,
and process lifecycle logic for the CitrixTranscriber backend.
"""

import json
import os
import sys
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.api_server import APIRequestHandler, LocalAPIServer, QuietThreadingHTTPServer

class TestLocalAPIServer(unittest.TestCase):
    """Test the LocalAPIServer and APIRequestHandler."""
    
    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        cls.test_port = 5055
        
    def setUp(self):
        # Create a thoroughly mocked Application instance
        self.mock_app = MagicMock()
        self.mock_app._program_active = True
        self.mock_app._current_processing_mode = None
        self.mock_app.begin_api_dictation_session.return_value = "sess_test_1"
        self.mock_app.get_status_snapshot.return_value = {
            "audioLevel": 42,
            "activeSessionId": None,
            "lastCompletedSessionId": "sess_prev",
        }
        self.mock_app.get_session_result.side_effect = lambda session_id: {
            "success": True,
            "sessionId": session_id,
            "state": "complete",
            "processedTranscript": "hello world",
            "historyEntryId": "hist_1",
            "completedAt": 123.4,
        }
        self.mock_app.is_stop_session_valid.return_value = True

        self.mock_audio_handler = MagicMock()
        self.mock_audio_handler._program_active = True
        self.mock_audio_handler.is_wake_word_enabled.return_value = True
        self.mock_audio_handler.get_listening_state.return_value = "activation"
        self.mock_app.audio_handler = self.mock_audio_handler
        
        self.server = LocalAPIServer(self.mock_app, port=self.test_port)
        self.server.start()
        time.sleep(0.5)  # Wait for server thread to bind and start
        
    def tearDown(self):
        if self.server:
            self.server.stop()
        time.sleep(0.5)
            
    def _send_request(self, endpoint, method="POST", data=None):
        url = f"http://127.0.0.1:{self.test_port}{endpoint}"
        body = None
        headers = {}
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=2) as response:
                status = response.getcode()
                data = json.loads(response.read().decode('utf-8'))
                return status, data
        except urllib.error.HTTPError as e:
            data = json.loads(e.read().decode('utf-8'))
            return e.code, data
            
    def test_status_endpoint(self):
        """Test the /status GET endpoint returns correctly formatted state."""
        status, data = self._send_request("/status", method="GET")
        
        self.assertEqual(status, 200)
        self.assertTrue(data.get("programActive"))
        self.assertEqual(data.get("audioState"), "activation")
        self.assertFalse(data.get("isDictating"))
        self.assertTrue(data.get("canDictate"))
        self.assertEqual(data.get("audioLevel"), 42)
        self.assertIsNone(data.get("activeSessionId"))
        self.assertEqual(data.get("lastCompletedSessionId"), "sess_prev")
        
    def test_start_dictation_success(self):
        """Test that /start successfully triggers dictation when active."""
        # Setup mock to simulate a successful transition to dictation
        def side_effect_wake_word(*args, **kwargs):
            self.mock_audio_handler.get_listening_state.return_value = "dictation"
            
        self.mock_app._handle_wake_word.side_effect = side_effect_wake_word
        
        status, data = self._send_request(
            "/start",
            method="POST",
            data={"source": "followup", "suppressPaste": True},
        )
        
        self.assertEqual(status, 200)
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("message"), "Dictation started")
        self.assertEqual(data.get("sessionId"), "sess_test_1")
        self.mock_app.begin_api_dictation_session.assert_called_once_with(
            suppress_paste=True,
            source="followup",
        )
        self.mock_app._handle_wake_word.assert_called_once()

    def test_start_dictation_success_without_body_backwards_compatible(self):
        """Test /start with no JSON body still works for legacy callers."""
        def side_effect_wake_word(*args, **kwargs):
            self.mock_audio_handler.get_listening_state.return_value = "dictation"

        self.mock_app._handle_wake_word.side_effect = side_effect_wake_word
        status, data = self._send_request("/start", method="POST")

        self.assertEqual(status, 200)
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("sessionId"), "sess_test_1")
        self.mock_app.begin_api_dictation_session.assert_called_with(
            suppress_paste=False,
            source=None,
        )
        
    def test_start_dictation_inactive_program(self):
        """Test that /start is ignored if program is inactive (mirrors hotkey behavior)."""
        self.mock_app._program_active = False
        
        status, data = self._send_request("/start", method="POST")
        
        self.assertEqual(status, 400)
        self.assertFalse(data.get("success"))
        self.assertIn("inactive", data.get("message"))
        self.mock_app._handle_wake_word.assert_not_called()
        
    def test_start_dictation_failed_transition(self):
        """Test /start fails if the audio handler rejects the transition."""
        # Audio handler stays in 'activation' despite wake word attempt
        self.mock_audio_handler.get_listening_state.return_value = "activation"
        
        status, data = self._send_request("/start", method="POST")
        
        self.assertEqual(status, 400)
        self.assertFalse(data.get("success"))
        self.assertIn("Failed to start dictation", data.get("message"))
        self.mock_app.clear_active_session.assert_called_once_with(as_not_found=True)

    def test_start_dictation_rejects_invalid_body_types(self):
        """Test /start body validation for source/suppressPaste."""
        status, data = self._send_request(
            "/start",
            method="POST",
            data={"source": 123, "suppressPaste": "yes"},
        )

        self.assertEqual(status, 400)
        self.assertFalse(data.get("success"))
        self.assertIn("suppressPaste", data.get("message", ""))
        
    def test_stop_dictation_success(self):
        """Test that /stop successfully stops dictation."""
        self.mock_audio_handler.get_listening_state.return_value = "dictation"
        self.mock_app.get_status_snapshot.return_value = {
            "audioLevel": 2,
            "activeSessionId": "sess_test_1",
            "lastCompletedSessionId": "sess_prev",
        }
        
        status, data = self._send_request(
            "/stop",
            method="POST",
            data={"sessionId": "sess_test_1"},
        )
        
        self.assertEqual(status, 200)
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("sessionId"), "sess_test_1")
        self.mock_app.is_stop_session_valid.assert_called_once_with("sess_test_1")
        self.mock_app._trigger_stop_dictation.assert_called_once()
        
    def test_stop_dictation_fails_when_not_dictating(self):
        """Test that /stop returns 400 when not dictating."""
        self.mock_audio_handler.get_listening_state.return_value = "activation"
        
        status, data = self._send_request("/stop", method="POST")
        
        self.assertEqual(status, 400)
        self.assertFalse(data.get("success"))
        self.mock_app._trigger_stop_dictation.assert_not_called()

    def test_stop_dictation_rejects_mismatched_session(self):
        """Test /stop rejects a session ID that does not match active session."""
        self.mock_app.is_stop_session_valid.return_value = False
        self.mock_audio_handler.get_listening_state.return_value = "dictation"

        status, data = self._send_request(
            "/stop",
            method="POST",
            data={"sessionId": "sess_other"},
        )

        self.assertEqual(status, 409)
        self.assertFalse(data.get("success"))
        self.assertIn("does not match", data.get("message", ""))
        self.mock_app._trigger_stop_dictation.assert_not_called()

    def test_result_endpoint(self):
        """Test /result returns session transcript payload."""
        status, data = self._send_request("/result?sessionId=sess_test_1", method="GET")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("sessionId"), "sess_test_1")
        self.assertEqual(data.get("state"), "complete")
        self.assertEqual(data.get("processedTranscript"), "hello world")

    def test_result_endpoint_requires_session_id(self):
        """Test /result without sessionId returns 400."""
        status, data = self._send_request("/result", method="GET")
        self.assertEqual(status, 400)
        self.assertFalse(data.get("success"))
        self.assertIn("Missing sessionId", data.get("message", ""))

    def test_status_endpoint_normalizes_unknown_audio_state(self):
        """Test /status coerces unsupported audio states to inactive."""
        self.mock_audio_handler.get_listening_state.return_value = "unexpected_state"
        status, data = self._send_request("/status", method="GET")
        self.assertEqual(status, 200)
        self.assertEqual(data.get("audioState"), "inactive")

    def test_result_endpoint_normalizes_unknown_result_state(self):
        """Test /result coerces unsupported session result states to not_found."""
        self.mock_app.get_session_result.side_effect = None
        self.mock_app.get_session_result.return_value = {
            "success": True,
            "sessionId": "sess_test_1",
            "state": "weird_state",
            "processedTranscript": "test",
            "historyEntryId": "hist_1",
            "completedAt": 100.0,
        }
        status, data = self._send_request("/result?sessionId=sess_test_1", method="GET")
        self.assertEqual(status, 200)
        self.assertEqual(data.get("state"), "not_found")

    def test_events_endpoint_streams_sse_status(self):
        """Test /events returns SSE stream with status payload."""
        url = f"http://127.0.0.1:{self.test_port}/events?sessionId=sess_test_1"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as response:
            self.assertEqual(response.getcode(), 200)
            self.assertEqual(response.headers.get_content_type(), "text/event-stream")
            line = response.readline().decode("utf-8")
            self.assertTrue(line.startswith("data: "))
            self.assertIn("\"audioState\"", line)

    def test_quiet_server_suppresses_expected_disconnect_tracebacks(self):
        """Expected client disconnects should not delegate to default traceback logging."""
        server = QuietThreadingHTTPServer(("127.0.0.1", 0), APIRequestHandler)
        try:
            err = ConnectionResetError(54, "Connection reset by peer")
            with patch("src.api_server.sys.exc_info", return_value=(ConnectionResetError, err, None)):
                with patch("src.api_server.ThreadingHTTPServer.handle_error") as mock_handle_error:
                    server.handle_error(None, ("127.0.0.1", 58835))
            mock_handle_error.assert_not_called()
        finally:
            server.server_close()

    def test_quiet_server_preserves_unexpected_tracebacks(self):
        """Unexpected server exceptions should still delegate to default error handling."""
        server = QuietThreadingHTTPServer(("127.0.0.1", 0), APIRequestHandler)
        try:
            err = RuntimeError("boom")
            with patch("src.api_server.sys.exc_info", return_value=(RuntimeError, err, None)):
                with patch("src.api_server.ThreadingHTTPServer.handle_error") as mock_handle_error:
                    server.handle_error(None, ("127.0.0.1", 58835))
            mock_handle_error.assert_called_once_with(None, ("127.0.0.1", 58835))
        finally:
            server.server_close()

if __name__ == "__main__":
    unittest.main()
