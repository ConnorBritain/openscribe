#!/usr/bin/env python3
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

# Add project root to import path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import main


class _ImmediateThread:
    """Thread shim that runs target synchronously for deterministic tests."""

    def __init__(self, target=None, daemon=None):
        self._target = target
        self.daemon = daemon

    def start(self):
        if self._target:
            self._target()


class TestQuickRetranscribeFallback(unittest.TestCase):
    def test_no_secondary_model_restores_previous_text(self):
        app = main.Application.__new__(main.Application)
        app._last_raw_transcription = "Recovered text"
        app._bg_retranscribe_result = None
        app._last_history_entry_id = None
        status_updates = []
        app._handle_status_update = lambda message, color: status_updates.append((message, color))

        with patch.object(main.settings_manager, "get_setting", return_value=None), \
            patch.object(main, "send_text_to_citrix") as mock_send:
            app._handle_retranscribe_secondary()

        mock_send.assert_called_once_with("Recovered text ")
        self.assertTrue(any("Restored previous text" in msg for msg, _ in status_updates))

    def test_empty_retranscribe_result_restores_previous_text(self):
        entry_id = "unit_retranscribe_entry"
        audio_dir = os.path.join("data", "history", "audio")
        audio_path = os.path.join(audio_dir, f"{entry_id}.wav")
        os.makedirs(audio_dir, exist_ok=True)
        with open(audio_path, "wb") as f:
            f.write(b"RIFF\x24\x00\x00\x00WAVE")

        app = main.Application.__new__(main.Application)
        app._last_raw_transcription = "Fallback text"
        app._bg_retranscribe_result = None
        app._last_history_entry_id = entry_id
        app.transcription_handler = SimpleNamespace(
            ensure_model_assets=lambda _model_id: None,
            retranscribe_audio_file=lambda _audio_path, _model_id: "",
        )
        status_updates = []
        app._handle_status_update = lambda message, color: status_updates.append((message, color))

        def _get_setting(key, default=None):
            if key == "secondaryAsrModel":
                return "mlx-community/whisper-large-v3-turbo"
            if key == "useMedGemmaPostProcessing":
                return False
            return default

        try:
            with patch.object(main.settings_manager, "get_setting", side_effect=_get_setting), \
                patch.object(main.threading, "Thread", _ImmediateThread), \
                patch.object(main, "send_text_to_citrix") as mock_send:
                app._handle_retranscribe_secondary()

            mock_send.assert_called_once_with("Fallback text ")
            self.assertTrue(any("Restored previous text" in msg for msg, _ in status_updates))
        finally:
            try:
                os.remove(audio_path)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
