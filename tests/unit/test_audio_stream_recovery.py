#!/usr/bin/env python3
"""
Unit tests for audio stream recovery after microphone route changes.
"""

import json
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import ipc_contract
from src.audio.audio_handler import AudioHandler


class FakeStream:
    """Minimal stream stub for audio handler recovery tests."""

    def __init__(self, *, active=True, frames=None):
        self._active = active
        self._frames = list(frames or [])
        self.closed = False
        self.read_calls = 0

    def is_active(self):
        return self._active and not self.closed

    def start_stream(self):
        self._active = True

    def stop_stream(self):
        self._active = False

    def close(self):
        self.closed = True
        self._active = False

    def read(self, frames, exception_on_overflow=False):
        self.read_calls += 1
        if self._frames:
            return self._frames.pop(0)
        return b"\x00" * (frames * 2)


class FakePyAudioBackend:
    """Minimal PyAudio backend stub for device lookup and open calls."""

    def __init__(self, device_info=None, opened_stream=None):
        self.device_info = dict(
            device_info
            or {
                "name": "Built-in Mic",
                "maxInputChannels": 1,
                "defaultSampleRate": 16000.0,
                "index": 0,
            }
        )
        self.opened_stream = opened_stream or FakeStream(active=True)
        self.terminated = False
        self.open_calls = []

    def open(self, **kwargs):
        self.open_calls.append(kwargs)
        return self.opened_stream

    def terminate(self):
        self.terminated = True

    def get_default_input_device_info(self):
        return dict(self.device_info)

    def get_device_info_by_index(self, index):
        info = dict(self.device_info)
        info["index"] = index
        return info

    def get_device_count(self):
        return 1


class TestAudioStreamRecovery(unittest.TestCase):
    """Validate automatic stream recovery for route churn."""

    def _make_handler(self):
        backend = FakePyAudioBackend()
        with patch("src.audio.audio_handler.pyaudio.PyAudio", return_value=backend):
            handler = AudioHandler()
        handler._p = backend
        events = []

        def capture(message, color):
            events.append((message, color))

        handler.on_status_update = capture
        return handler, backend, events

    def _state_payloads(self, events):
        payloads = []
        for message, _color in events:
            if ipc_contract.is_prefixed_message(message, "state"):
                payloads.append(
                    json.loads(ipc_contract.strip_prefix(message, "state") or "{}")
                )
        return payloads

    def test_inactive_stream_schedules_recovery_instead_of_exiting(self):
        handler, _backend, _events = self._make_handler()
        handler._stream = FakeStream(active=False)
        handler._program_active = True
        handler._listening_state = "activation"
        handler._stop_event = threading.Event()

        recovery_attempted = []

        def conditional_attempt():
            if handler._pending_stream_recovery:
                recovery_attempted.append(True)
                handler._stop_event.set()

        with patch.object(handler, "_attempt_scheduled_recovery", side_effect=conditional_attempt):
            with patch.object(handler, "_poll_default_input_route", return_value=None):
                with patch.object(handler, "_log_memory_usage", return_value=None):
                    with patch("src.audio.audio_handler.time.sleep", return_value=None):
                        handler._run_loop()

        self.assertTrue(handler._pending_stream_recovery)
        self.assertEqual(handler._listening_state, "preparing")
        self.assertTrue(recovery_attempted)

    def test_default_device_signature_change_reopens_stream(self):
        handler, _backend, events = self._make_handler()
        old_signature = handler._device_signature(
            None,
            {
                "name": "USB Headset",
                "maxInputChannels": 1,
                "defaultSampleRate": 48000.0,
                "index": 3,
            },
        )
        new_device_info = {
            "name": "Built-in Mic",
            "maxInputChannels": 1,
            "defaultSampleRate": 16000.0,
            "index": 0,
        }
        handler._stream = FakeStream(active=True)
        handler._program_active = True
        handler._listening_state = "activation"
        handler._input_device_preference = "default"
        handler._last_stream_device_signature = old_signature
        handler._p = FakePyAudioBackend(device_info=new_device_info)

        def replace_stream(*, reset_pyaudio=False):
            self.assertTrue(reset_pyaudio)
            handler._stream = FakeStream(active=True)
            handler._last_stream_device_signature = handler._device_signature(
                None, new_device_info
            )
            return dict(new_device_info)

        with patch.object(handler, "_replace_audio_stream", side_effect=replace_stream):
            handler._poll_default_input_route(force=True)
            self.assertTrue(handler._pending_stream_recovery)
            handler._stream_recovery_next_attempt_at = 0.0
            handler._attempt_scheduled_recovery()

        self.assertFalse(handler._pending_stream_recovery)
        self.assertEqual(handler.get_listening_state(), "activation")
        self.assertEqual(
            handler._last_stream_device_signature["name"],
            new_device_info["name"],
        )
        self.assertTrue(
            any("Microphone reconnected." in message for message, _ in events)
        )

    def test_all_zero_frame_streak_triggers_recovery(self):
        handler, _backend, _events = self._make_handler()
        handler._zero_frame_recovery_threshold = 3
        handler._stream = FakeStream(active=True)
        handler._program_active = True
        handler._listening_state = "activation"
        silent_frame = np.zeros(handler._stream_frame_size, dtype=np.int16)

        for _ in range(3):
            handler._check_main_loop_audio_health(silent_frame)

        self.assertTrue(handler._pending_stream_recovery)
        self.assertEqual(handler._stream_recovery_reason, "zero_frames")
        self.assertEqual(handler.get_listening_state(), "preparing")

    def test_mid_dictation_route_change_cancels_capture_and_returns_to_activation(self):
        handler, _backend, events = self._make_handler()
        handler._stream = FakeStream(active=True)
        handler._program_active = True
        handler._listening_state = "dictation"
        handler._triggered = True
        handler._voiced_frames = [np.array([1, 2, 3], dtype=np.int16)]

        reconnected_device = {
            "name": "Reconnected Mic",
            "maxInputChannels": 1,
            "defaultSampleRate": 16000.0,
            "index": 2,
        }

        def replace_stream(*, reset_pyaudio=False):
            self.assertTrue(reset_pyaudio)
            handler._stream = FakeStream(active=True)
            handler._last_stream_device_signature = handler._device_signature(
                None, reconnected_device
            )
            return dict(reconnected_device)

        with patch.object(handler, "_replace_audio_stream", side_effect=replace_stream):
            handler._schedule_stream_recovery(
                "route_changed",
                "Microphone connection changed. Reconnecting audio...",
                immediate=True,
            )
            self.assertEqual(handler.get_listening_state(), "preparing")
            self.assertEqual(handler._voiced_frames, [])
            self.assertFalse(handler._triggered)
            handler._stream_recovery_next_attempt_at = 0.0
            handler._attempt_scheduled_recovery()

        self.assertFalse(handler._pending_stream_recovery)
        self.assertEqual(handler.get_listening_state(), "activation")
        status_texts = [message for message, color in events if color != "STATE_MSG"]
        self.assertTrue(
            any("Current dictation was canceled" in message for message in status_texts)
        )
        self.assertTrue(any("Microphone reconnected." in message for message in status_texts))

    def test_recovery_sets_microphone_error_after_fast_retry_exhaustion(self):
        handler, _backend, events = self._make_handler()
        handler._stream = FakeStream(active=True)
        handler._program_active = True
        handler._listening_state = "activation"
        handler._schedule_stream_recovery(
            "stream_inactive",
            "Audio input became unavailable. Reconnecting microphone...",
            immediate=True,
        )

        with patch.object(
            handler, "_replace_audio_stream", side_effect=RuntimeError("No such device")
        ):
            for _ in range(5):
                handler._stream_recovery_next_attempt_at = 0.0
                handler._attempt_scheduled_recovery()

        state_payloads = self._state_payloads(events)
        error_payloads = [
            payload for payload in state_payloads if payload.get("microphoneError")
        ]
        self.assertTrue(handler._pending_stream_recovery)
        self.assertTrue(handler._stream_recovery_error_emitted)
        self.assertTrue(error_payloads)
        self.assertIn("No such device", error_payloads[-1]["microphoneError"])
        self.assertEqual(handler._mic_error_details[0], False)

    def test_background_retry_recovers_when_device_returns(self):
        handler, _backend, events = self._make_handler()
        handler._stream = FakeStream(active=True)
        handler._program_active = True
        handler._listening_state = "activation"
        handler._schedule_stream_recovery(
            "read_error",
            "Audio input encountered a device change. Reconnecting microphone...",
            immediate=True,
        )

        reconnected_device = {
            "name": "Recovered Mic",
            "maxInputChannels": 1,
            "defaultSampleRate": 16000.0,
            "index": 5,
        }
        attempts = {"count": 0}

        def replace_stream(*, reset_pyaudio=False):
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise RuntimeError("No such device")
            handler._stream = FakeStream(active=True)
            handler._last_stream_device_signature = handler._device_signature(
                None, reconnected_device
            )
            return dict(reconnected_device)

        with patch.object(handler, "_replace_audio_stream", side_effect=replace_stream):
            for _ in range(3):
                handler._stream_recovery_next_attempt_at = 0.0
                handler._attempt_scheduled_recovery()

        self.assertEqual(attempts["count"], 3)
        self.assertFalse(handler._pending_stream_recovery)
        self.assertEqual(handler.get_listening_state(), "activation")
        error_payloads = [
            payload
            for payload in self._state_payloads(events)
            if payload.get("microphoneError")
        ]
        self.assertEqual(error_payloads, [])


if __name__ == "__main__":
    unittest.main()
