#!/usr/bin/env python3
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

# Add project root to import path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import main
from src.text_insertion.safe_text_inserter import InsertResult, SafeTextInserter


class _DeferredThread:
    created = []

    def __init__(self, target=None, daemon=None):
        self.target = target
        self.daemon = daemon
        _DeferredThread.created.append(self)

    def start(self):
        # Intentionally deferred for deterministic assertions.
        return


class _RecordingInserter:
    def __init__(self):
        self.insert_calls = []
        self.pending_messages = []

    def notify_pending(self, message):
        self.pending_messages.append(message)

    def transactional_insert(self, **kwargs):
        self.insert_calls.append(kwargs)
        inserted_text = ""
        if isinstance(kwargs.get("primary_text"), str):
            inserted_text = kwargs["primary_text"].strip()
        elif isinstance(kwargs.get("fallback_text"), str):
            inserted_text = kwargs["fallback_text"].strip()
        return InsertResult(
            success=bool(inserted_text),
            inserted_text=inserted_text,
            used_fallback=not bool(kwargs.get("primary_text", "").strip()),
            reason="test",
        )


class TestSafeTextInserter(unittest.TestCase):
    def test_empty_primary_and_fallback_never_calls_paste(self):
        paste_calls = []
        status_messages = []
        inserter = SafeTextInserter(
            paste_callback=lambda text: paste_calls.append(text),
            status_callback=lambda message, color: status_messages.append((message, color)),
        )

        result = inserter.transactional_insert(
            primary_text="",
            fallback_text="",
            source="transcription",
        )

        self.assertFalse(result.success)
        self.assertEqual(paste_calls, [])
        self.assertTrue(any("left unchanged" in message for message, _ in status_messages))


class TestInsertionSafetyIntegration(unittest.TestCase):
    def test_retranscribe_model_loading_waits_for_result_before_insert(self):
        _DeferredThread.created.clear()
        app = main.Application.__new__(main.Application)
        app._last_raw_transcription = "Existing text"
        app._bg_retranscribe_result = None
        app._last_history_entry_id = "entry_loading"
        app._current_processing_mode = None
        app._handle_status_update = lambda *_args, **_kwargs: None
        app.audio_handler = SimpleNamespace(
            get_listening_state=lambda: "activation",
            _program_active=True,
            is_wake_word_enabled=lambda: True,
        )
        app.transcription_handler = SimpleNamespace(
            ensure_model_assets=lambda _model_id: None,
            retranscribe_audio_file=lambda _audio_path, _model_id: "Fresh model result",
        )
        inserter = _RecordingInserter()
        app._text_inserter = inserter

        def _get_setting(key, default=None):
            if key == "secondaryAsrModel":
                return "mlx-community/whisper-large-v3-turbo"
            if key == "useMedGemmaPostProcessing":
                return False
            return default

        with patch.object(main.settings_manager, "get_setting", side_effect=_get_setting), \
            patch.object(main.os.path, "exists", return_value=True), \
            patch.object(main.threading, "Thread", _DeferredThread):
            app._handle_retranscribe_secondary()

        # During "model loading", no insertion should happen yet.
        self.assertEqual(len(inserter.insert_calls), 0)
        self.assertEqual(len(inserter.pending_messages), 1)
        self.assertEqual(len(_DeferredThread.created), 1)

        # Once worker runs and result exists, insertion happens exactly once.
        _DeferredThread.created[0].target()
        self.assertEqual(len(inserter.insert_calls), 1)
        self.assertEqual(
            inserter.insert_calls[0].get("primary_text"),
            "Fresh model result",
        )

    def test_abort_dictation_does_not_trigger_text_insert(self):
        app = main.Application.__new__(main.Application)
        app.audio_handler = SimpleNamespace(abort_dictation=lambda: None)
        app.hotkey_manager = SimpleNamespace(set_dictating_state=lambda _state: None)
        app.clear_active_session = lambda **_kwargs: None
        app._update_app_state = lambda: None
        app._pending_audio_bytes = b"abc"
        app._current_dictation_started_at = 123.0
        inserter = _RecordingInserter()
        app._text_inserter = inserter

        app._trigger_abort_dictation()

        self.assertEqual(inserter.insert_calls, [])


if __name__ == "__main__":
    unittest.main()

