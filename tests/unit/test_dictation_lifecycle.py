#!/usr/bin/env python3
import os
import sys
import unittest

# Add project root to import path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.dictation_lifecycle import DictationLifecycleStateMachine


class TestDictationLifecycleStateMachine(unittest.TestCase):
    def test_manual_transition_sequence(self):
        lifecycle = DictationLifecycleStateMachine(initial_state="idle")
        lifecycle.transition("listening", reason="ready")
        lifecycle.transition("recording", reason="hotkey")
        lifecycle.transition("stopping", reason="manual_stop")
        lifecycle.transition("transcribing", reason="speech_end")
        lifecycle.transition("inserting", reason="text_ready")
        lifecycle.transition("listening", reason="complete")

        snapshot = lifecycle.snapshot()
        self.assertEqual(snapshot.state, "listening")
        self.assertEqual(snapshot.previous_state, "inserting")

    def test_sync_from_audio_state_maps_expected_states(self):
        lifecycle = DictationLifecycleStateMachine(initial_state="idle")
        self.assertEqual(
            lifecycle.sync_from_audio_state(
                audio_state="activation",
                program_active=True,
                wake_word_enabled=True,
                reason="activation",
            ),
            "listening",
        )
        self.assertEqual(
            lifecycle.sync_from_audio_state(
                audio_state="dictation",
                program_active=True,
                wake_word_enabled=True,
                reason="dictation",
            ),
            "recording",
        )
        self.assertEqual(
            lifecycle.sync_from_audio_state(
                audio_state="processing",
                program_active=True,
                wake_word_enabled=True,
                reason="processing",
            ),
            "transcribing",
        )

    def test_invalid_transition_raises(self):
        lifecycle = DictationLifecycleStateMachine(initial_state="idle")
        with self.assertRaises(ValueError):
            lifecycle.transition("inserting", reason="invalid")


if __name__ == "__main__":
    unittest.main()

