import json
import sys
import threading
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Optional
from urllib.parse import parse_qs, urlparse
from src.config import config
from src.utils.utils import log_text
from src.contracts.generated_contract import AUDIO_STATES, RESULT_STATES


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    """Suppress noisy tracebacks for expected local client disconnects."""

    def handle_error(self, request, client_address):
        _, err, _ = sys.exc_info()
        if isinstance(err, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)

class APIRequestHandler(BaseHTTPRequestHandler):
    """
    HTTP Request Handler that routes requests to the Application core.
    We pass the `Application` instance to the server, and the handler
    retrieves it via `self.server.app`.
    """
    
    def _send_response(self, status_code: int, message: str, success: bool = True, extra: Optional[dict] = None):
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()

        response = {
            "success": success,
            "message": message
        }
        if extra:
            response.update(extra)
        self.wfile.write(json.dumps(response).encode('utf-8'))

    def _send_json(self, status_code: int, payload: dict):
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode('utf-8'))

    def _read_json_body(self):
        content_length = int(self.headers.get('Content-Length') or 0)
        if content_length <= 0:
            return {}
        try:
            raw = self.rfile.read(content_length).decode('utf-8')
            if not raw.strip():
                return {}
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
            raise ValueError("Body must be a JSON object")
        except Exception as err:
            raise ValueError(f"Invalid JSON body: {err}")

    def do_POST(self):
        """Handle POST requests for starting and stopping dictation."""
        app = getattr(self.server, 'app', None)
        parsed_url = urlparse(self.path)
        route = parsed_url.path

        if not app:
            self._send_response(500, "Application instance not available in API server", success=False)
            return

        try:
            body = self._read_json_body()
        except ValueError as err:
            self._send_response(400, str(err), success=False)
            return

        if route == '/start':
            log_text("API", "Received /start POST request")

            # Match hotkey logic: explicitly ignore start if program is inactive
            if getattr(app, '_program_active', False) is False:
                self._send_response(400, "Program is inactive, ignoring start command", success=False)
                return

            current_audio_state = app.audio_handler.get_listening_state()
            if current_audio_state == "dictation":
                self._send_response(400, "Already dictating", success=False)
            elif current_audio_state == "processing":
                self._send_response(400, "Currently processing", success=False)
            else:
                suppress_paste_raw = body.get("suppressPaste", False)
                if "suppressPaste" in body and not isinstance(suppress_paste_raw, bool):
                    self._send_response(400, "suppressPaste must be a boolean when provided", success=False)
                    return
                suppress_paste = bool(suppress_paste_raw)
                source = body.get("source")
                if source is not None and not isinstance(source, str):
                    self._send_response(400, "source must be a string when provided", success=False)
                    return
                session_id = None
                if hasattr(app, "begin_api_dictation_session"):
                    session_id = app.begin_api_dictation_session(
                        suppress_paste=suppress_paste,
                        source=source if isinstance(source, str) else None,
                    )

                # Trigger the wake word behavior to start dictation
                app._handle_wake_word(config.COMMAND_START_DICTATE)

                # Check if audio state actually transitioned
                new_audio_state = app.audio_handler.get_listening_state()
                if new_audio_state == "dictation":
                    self._send_response(200, "Dictation started", extra={"sessionId": session_id})
                else:
                    if hasattr(app, "clear_active_session"):
                        app.clear_active_session(as_not_found=True)
                    self._send_response(400, "Failed to start dictation (microphone may not be available)", success=False)

        elif route == '/stop':
            log_text("API", "Received /stop POST request")
            requested_session_id = body.get("sessionId")
            if requested_session_id is not None and not isinstance(requested_session_id, str):
                self._send_response(400, "sessionId must be a string when provided", success=False)
                return
            if hasattr(app, "is_stop_session_valid") and not app.is_stop_session_valid(requested_session_id):
                self._send_response(409, "Provided sessionId does not match active dictation session", success=False)
                return

            current_audio_state = app.audio_handler.get_listening_state()
            if current_audio_state == "dictation":
                app._trigger_stop_dictation()
                status_snapshot = app.get_status_snapshot() if hasattr(app, "get_status_snapshot") else {}
                self._send_response(
                    200,
                    "Dictation stopped and processing started",
                    extra={"sessionId": status_snapshot.get("activeSessionId")},
                )
            else:
                self._send_response(400, "Not currently dictating", success=False)

        elif route == '/status':
            log_text("API", "Received /status POST request")
            self._send_status()

        else:
            self._send_response(404, f"Endpoint not found: {route}", success=False)

    def do_GET(self):
        """Handle GET requests, mainly for a status check."""
        parsed_url = urlparse(self.path)
        route = parsed_url.path
        if route == '/status':
            self._send_status()
        elif route == '/result':
            self._send_result(parsed_url.query)
        elif route == '/events':
            self._send_events(parsed_url.query)
        elif route == '/':
            self._send_response(200, "CitrixTranscriber Local API Running")
        else:
            self._send_response(404, f"Endpoint not found: {route}", success=False)

    def _build_status_payload(self):
        app = getattr(self.server, 'app', None)
        if not app:
            return None
            
        audio_state = app.audio_handler.get_listening_state()
        if audio_state not in AUDIO_STATES:
            audio_state = "inactive"
        is_dictating = audio_state == "dictation"
        
        # safely handle missing attributes during startup config
        audio_handler_active = getattr(app.audio_handler, '_program_active', False)
        wake_word_enabled = False
        if hasattr(app.audio_handler, 'is_wake_word_enabled'):
            wake_word_enabled = app.audio_handler.is_wake_word_enabled()
            
        can_dictate = audio_handler_active and audio_state == "activation" and wake_word_enabled

        session_snapshot = app.get_status_snapshot() if hasattr(app, "get_status_snapshot") else {}
        return {
            "programActive": audio_handler_active,
            "audioState": audio_state,
            "isDictating": is_dictating,
            "canDictate": can_dictate,
            "currentMode": getattr(app, '_current_processing_mode', None),
            "wakeWordEnabled": wake_word_enabled,
            "audioLevel": session_snapshot.get("audioLevel", 0),
            "activeSessionId": session_snapshot.get("activeSessionId"),
            "lastCompletedSessionId": session_snapshot.get("lastCompletedSessionId"),
        }

    def _send_status(self):
        """Send the current application state."""
        state = self._build_status_payload()
        if state is None:
            self._send_response(500, "Application instance not available in API server", success=False)
            return
        self._send_json(200, state)

    def _send_events(self, query: str):
        app = getattr(self.server, 'app', None)
        if not app:
            self._send_response(500, "Application instance not available in API server", success=False)
            return

        query_params = parse_qs(query or "")
        requested_session_id = (query_params.get("sessionId") or [None])[0]
        if requested_session_id is not None and not isinstance(requested_session_id, str):
            self._send_response(400, "sessionId must be a string when provided", success=False)
            return

        self.send_response(200)
        self.send_header('Content-type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.end_headers()

        started_at = time.time()
        max_stream_seconds = 90
        heartbeat_seconds = 1.0
        poll_interval_seconds = 0.2
        last_emit_at = 0.0
        last_payload_json = None

        try:
            while True:
                now = time.time()
                if now - started_at > max_stream_seconds:
                    break

                payload = self._build_status_payload()
                if payload is None:
                    break

                payload_json = json.dumps(payload)
                should_emit = payload_json != last_payload_json or (now - last_emit_at) >= heartbeat_seconds
                if should_emit:
                    self.wfile.write(f"data: {payload_json}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    last_payload_json = payload_json
                    last_emit_at = now

                time.sleep(poll_interval_seconds)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as err:
            log_text("API", f"Status stream closed with error: {err}")
            return

    def _send_result(self, query: str):
        app = getattr(self.server, 'app', None)
        if not app:
            self._send_response(500, "Application instance not available in API server", success=False)
            return

        query_params = parse_qs(query or "")
        session_id = (query_params.get("sessionId") or [None])[0]
        if not session_id:
            self._send_response(400, "Missing sessionId query parameter", success=False)
            return

        if hasattr(app, "get_session_result"):
            payload = app.get_session_result(session_id)
        else:
            payload = {
                "success": True,
                "sessionId": session_id,
                "state": "not_found",
                "processedTranscript": "",
                "historyEntryId": None,
                "completedAt": None,
            }

        state_value = payload.get("state")
        if state_value not in RESULT_STATES:
            payload["state"] = "not_found"
        self._send_json(200, payload)

    def log_message(self, format, *args):
        """Override to use our custom logger instead of stderr"""
        if not getattr(config, "MINIMAL_TERMINAL_OUTPUT", False):
            # Only print HTTP logs if not in minimal output mode
            super().log_message(format, *args)


class LocalAPIServer:
    """Manager for the background HTTP server."""
    
    def __init__(self, application_instance, port=None):
        self.app = application_instance
        self.port = port or getattr(config, 'LOCAL_API_PORT', 5050)
        self.server = None
        self.server_thread = None
        
    def start(self):
        """Start the HTTP server in a daemon thread."""
        try:
            # We map 127.0.0.1 to ensure local-only binding
            self.server = QuietThreadingHTTPServer(('127.0.0.1', self.port), APIRequestHandler)
            
            # Attach application context to server object so handlers can access it
            self.server.app = self.app
            
            self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.server_thread.start()
            
            log_text("API", f"Local API started on port {self.port}")
            if not getattr(config, "MINIMAL_TERMINAL_OUTPUT", False):
                print(f"[API] Local API Server started on http://127.0.0.1:{self.port}")
                
        except Exception as e:
            log_text("ERROR", f"Failed to start Local API Server on port {self.port}: {e}")
            print(f"[ERROR] Failed to start Local API: {e}")
            
    def stop(self):
        """Gracefully shutdown the API server."""
        if self.server:
            log_text("API", "Shutting down Local API Server")
            # shutdown() and server_close() ensure the port is freed and the thread exits
            self.server.shutdown()
            self.server.server_close()
            if self.server_thread and self.server_thread.is_alive():
                self.server_thread.join(timeout=2)
            self.server = None
            self.server_thread = None
