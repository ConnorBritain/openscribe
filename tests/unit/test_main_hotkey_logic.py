import os
import sys
import unittest

# Add project root to import path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from main import Application
from src.config import config


class TestMainHotkeyLogic(unittest.TestCase):
    def setUp(self):
        self.app = Application.__new__(Application)
        self.events = []

        self.app._handle_status_update = (
            lambda message, color: self.events.append(("status", message, color))
        )
        self.app._handle_wake_word = (
            lambda command: self.events.append(("wake_word", command))
        )
        self.app._trigger_stop_dictation = (
            lambda: self.events.append(("stop_dictation",))
        )

    def test_start_dictate_hotkey_starts_when_idle(self):
        started = self.app._handle_start_dictate_hotkey("activation", "test_start")
        self.assertTrue(started)
        self.assertIn(("wake_word", config.COMMAND_START_DICTATE), self.events)

    def test_start_dictate_hotkey_ignored_when_already_dictating(self):
        started = self.app._handle_start_dictate_hotkey("dictation", "test_start")
        self.assertFalse(started)
        self.assertIn(
            ("status", "Already dictating, ignoring start command.", "orange"),
            self.events,
        )

    def test_start_dictate_hotkey_ignored_while_processing(self):
        started = self.app._handle_start_dictate_hotkey("processing", "test_start")
        self.assertFalse(started)
        self.assertIn(
            ("status", "Currently processing, ignoring start command.", "orange"),
            self.events,
        )

    def test_toggle_dictate_hotkey_stops_when_dictating(self):
        self.app._handle_toggle_dictate_hotkey("dictation")
        self.assertEqual(self.events, [("stop_dictation",)])

    def test_toggle_dictate_hotkey_ignored_while_processing(self):
        self.app._handle_toggle_dictate_hotkey("processing")
        self.assertIn(
            ("status", "Currently processing, toggle ignored.", "orange"),
            self.events,
        )

    def test_toggle_dictate_hotkey_starts_when_idle(self):
        self.app._handle_toggle_dictate_hotkey("activation")
        self.assertIn(("wake_word", config.COMMAND_START_DICTATE), self.events)

    def test_stop_dictate_hotkey_stops_when_dictating(self):
        self.app._handle_stop_dictate_hotkey("dictation")
        self.assertEqual(self.events, [("stop_dictation",)])

    def test_stop_dictate_hotkey_ignored_when_not_dictating(self):
        self.app._handle_stop_dictate_hotkey("activation")
        self.assertIn(
            ("status", "Not dictating, stop command ignored.", "orange"),
            self.events,
        )


if __name__ == "__main__":
    unittest.main()
