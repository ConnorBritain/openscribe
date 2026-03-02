import os
import sys
import time
import unittest

# Add project root to import path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.config import config
from src.hotkey_manager import HotkeyManager, parse_shortcut_to_combo


class TestHotkeyManagerDeferredDispatch(unittest.TestCase):
    def setUp(self):
        self._original_hotkeys = config.HOTKEY_COMBINATIONS
        self.events = []
        self.manager = HotkeyManager(on_hotkey_callback=self.events.append)
        # Keep tests deterministic and independent from pynput types.
        self.manager._normalize_key = lambda key: key

        self.cmd = object()
        self.shift = object()
        self.x = object()
        config.HOTKEY_COMBINATIONS = {
            frozenset({self.cmd, self.shift, self.x}): "test_combo"
        }

    def tearDown(self):
        config.HOTKEY_COMBINATIONS = self._original_hotkeys

    def test_dispatch_happens_after_all_keys_release(self):
        self.manager._current_keys = {self.cmd, self.shift, self.x}

        self.manager._on_release(self.x)
        self.assertEqual(self.events, [])

        self.manager._on_release(self.shift)
        self.assertEqual(self.events, [])

        self.manager._on_release(self.cmd)
        self.assertEqual(self.events, ["test_combo"])

    def test_pending_combo_timeout_dispatches_even_if_key_state_is_stale(self):
        self.manager._pending_command_timeout_seconds = 0.001
        self.manager._current_keys = {self.cmd, self.shift, self.x}

        self.manager._on_release(self.x)
        time.sleep(0.01)

        # One modifier remains "stuck"; timeout should still dispatch.
        self.manager._on_release(self.shift)
        self.assertEqual(self.events, ["test_combo"])
        self.assertEqual(self.manager._current_keys, set())

    def test_suspended_hotkeys_do_not_dispatch(self):
        self.manager.set_hotkeys_suspended(True)
        self.manager._current_keys = {self.cmd, self.shift, self.x}

        self.manager._on_release(self.x)
        self.manager._on_release(self.shift)
        self.manager._on_release(self.cmd)

        self.assertEqual(self.events, [])
        self.assertEqual(self.manager._current_keys, set())

    def test_hotkeys_dispatch_again_after_resuming(self):
        self.manager.set_hotkeys_suspended(True)
        self.manager.set_hotkeys_suspended(False)
        self.manager._current_keys = {self.cmd, self.shift, self.x}

        self.manager._on_release(self.x)
        self.manager._on_release(self.shift)
        self.manager._on_release(self.cmd)

        self.assertEqual(self.events, ["test_combo"])


class TestConfigRetranscribeHotkeys(unittest.TestCase):
    def test_retranscribe_has_shift_option_and_safe_fallback_variants(self):
        combos = [
            combo
            for combo, command in config.HOTKEY_COMBINATIONS.items()
            if command == config.COMMAND_RETRANSCRIBE_SECONDARY
        ]

        self.assertGreaterEqual(len(combos), 3)
        self.assertTrue(any(config.Key.shift in combo for combo in combos))
        self.assertTrue(any(config.Key.alt in combo for combo in combos))
        self.assertTrue(any(config.Key.ctrl in combo and config.Key.alt in combo for combo in combos))

    def test_toggle_dictate_has_alt_space_combo(self):
        combos = [
            combo
            for combo, command in config.HOTKEY_COMBINATIONS.items()
            if command == config.COMMAND_TOGGLE_DICTATE
        ]
        self.assertGreaterEqual(len(combos), 1)
        self.assertTrue(any(config.Key.alt in combo and config.Key.space in combo for combo in combos))


class TestShortcutBindingRules(unittest.TestCase):
    def test_same_transcribe_and_stop_shortcut_behaves_as_toggle(self):
        manager = HotkeyManager(on_hotkey_callback=lambda _command: None)
        manager.update_shortcut_bindings(
            {
                "transcribe": "Option+Space",
                "stopTranscribing": "Option+Space",
                "retranscribeBackup": "Ctrl+Option+R",
            }
        )

        combo = parse_shortcut_to_combo("Option+Space")
        self.assertIsNotNone(combo)
        hotkeys = manager.get_hotkey_combinations()

        self.assertEqual(hotkeys.get(combo), config.COMMAND_TOGGLE_DICTATE)
        self.assertNotIn(config.COMMAND_STOP_DICTATE, hotkeys.values())


if __name__ == "__main__":
    unittest.main()
