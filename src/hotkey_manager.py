# Make pynput imports conditional for CI compatibility
try:
        from pynput import keyboard
        PYNPUT_AVAILABLE = True
except ImportError:
    # pynput not available (CI environment)
    PYNPUT_AVAILABLE = False
    print("[WARN] pynput not available in hotkey_manager.py - using mock classes")
    # Create a minimal mock keyboard module
    class MockKeyboard:
        class Key:
            cmd = "cmd"
            shift = "shift"
            ctrl = "ctrl"
            alt = "alt"
            space = "space"
            
        class KeyCode:
            def __init__(self, char=None):
                self.char = char
            
            @staticmethod
            def from_char(char):
                return MockKeyboard.KeyCode(char)
        
        class Listener:
            def __init__(self, on_press=None, on_release=None):
                self.on_press = on_press
                self.on_release = on_release
            
            def start(self):
                pass
            
            def stop(self):
                pass
            
            def join(self):
                pass
    
    keyboard = MockKeyboard()

import threading
import time
import re

# Import configuration constants
from src.config import config
from src.utils.utils import log_text


def _canonicalize_shortcut_tokens(shortcut: str):
    if not isinstance(shortcut, str):
        return []
    raw_tokens = [token.strip() for token in shortcut.replace(" ", "").split("+")]
    return [token for token in raw_tokens if token]


def _token_to_key(token: str):
    normalized = token.lower()
    modifier_map = {
        "cmd": getattr(keyboard.Key, "cmd", None),
        "command": getattr(keyboard.Key, "cmd", None),
        "ctrl": getattr(keyboard.Key, "ctrl", None),
        "control": getattr(keyboard.Key, "ctrl", None),
        "alt": getattr(keyboard.Key, "alt", None),
        "option": getattr(keyboard.Key, "alt", None),
        "shift": getattr(keyboard.Key, "shift", None),
        "space": getattr(keyboard.Key, "space", None),
    }
    if normalized in modifier_map:
        return modifier_map[normalized]

    if len(token) == 1 and re.match(r"[A-Za-z0-9]", token):
        return keyboard.KeyCode.from_char(token.lower())

    return None


def parse_shortcut_to_combo(shortcut: str):
    tokens = _canonicalize_shortcut_tokens(shortcut)
    if not tokens:
        return None

    keys = set()
    for token in tokens:
        resolved = _token_to_key(token)
        if resolved is None:
            return None
        keys.add(resolved)

    return frozenset(keys) if keys else None


def build_default_hotkey_bindings():
    return dict(config.HOTKEY_COMBINATIONS)


class HotkeyManager:
    """Manages global hotkey listeners using pynput."""

    def __init__(self, on_hotkey_callback=None, on_status_update_callback=None):
        """
        Initializes the HotkeyManager.

        Args:
            on_hotkey_callback: Function to call when a registered hotkey combination is pressed.
                                Receives the command string associated with the hotkey.
            on_status_update_callback: Function to call to update the application status display.
                                       Receives status text (str) and color (str).
        """
        self.on_hotkey = on_hotkey_callback
        self.on_status_update = on_status_update_callback
        self._listener_thread = None
        self._listener = None
        self._stop_event = threading.Event()
        self._current_keys = set()  # Keep track of currently pressed keys
        self._is_dictating = False  # Track if dictation mode is active
        self._pending_command = None  # Defer dispatch until all combo keys are released
        self._pending_command_armed_at = 0.0
        self._pending_command_timeout_seconds = 0.75
        self._hotkey_combinations = None  # None means follow config.HOTKEY_COMBINATIONS dynamically
        self._hotkeys_suspended = False  # Temporarily disable dispatch (e.g., while editing shortcuts)

    def _get_active_hotkey_combinations(self):
        if self._hotkey_combinations is None:
            return config.HOTKEY_COMBINATIONS
        return self._hotkey_combinations

    def set_dictating_state(self, is_dictating: bool):
        """Update the dictation state."""
        self._is_dictating = is_dictating
        # log_text("HOTKEY_DEBUG", f"Dictation state set to: {self._is_dictating}")

    def set_hotkeys_suspended(self, suspended: bool):
        """Temporarily suspend hotkey dispatch without stopping the listener."""
        suspended_bool = bool(suspended)
        if self._hotkeys_suspended == suspended_bool:
            return
        self._hotkeys_suspended = suspended_bool
        self._current_keys.clear()
        self._clear_pending_command()
        if suspended_bool:
            self._log_status("Hotkey dispatch suspended.", "grey")
        else:
            self._log_status("Hotkey dispatch resumed.", "grey")

    def _dispatch_hotkey_command(self, command: str):
        """Dispatch a hotkey command through the registered callback."""
        if self.on_hotkey:
            try:
                self.on_hotkey(command)
            except Exception as e:
                self._log_status(
                    f"Error executing hotkey callback for '{command}': {e}",
                    "red",
                )

    def _clear_pending_command(self):
        self._pending_command = None
        self._pending_command_armed_at = 0.0

    def _dispatch_pending_command_if_ready(self, force: bool = False):
        """Dispatch deferred combo once all keys are released (or forced on timeout)."""
        if not self._pending_command:
            return
        if not force and self._current_keys:
            return

        pending = self._pending_command
        self._clear_pending_command()
        self._dispatch_hotkey_command(pending)

    def _log_status(self, message, color="black"):
        """Helper to call the status update callback if available."""
        import sys
        print(f"HotkeyManager Status: {message}", file=sys.stderr)  # stderr to avoid IPC noise
        if self.on_status_update:
            self.on_status_update(message, color)

    def _normalize_key(self, key):
        """Normalize key representation for consistent comparison."""
        # For special keys, return the key object itself.
        # For character keys, return the KeyCode object with lowercase char
        # so that Shift+X still matches config's KeyCode.from_char('x').
        if hasattr(key, "char") and key.char:
            return keyboard.KeyCode.from_char(key.char.lower())
        # Normalize left/right modifier variants so combos stay reliable.
        modifier_groups = (
            ("cmd", ("cmd_l", "cmd_r")),
            ("shift", ("shift_l", "shift_r")),
            ("ctrl", ("ctrl_l", "ctrl_r")),
            ("alt", ("alt_l", "alt_r", "alt_gr")),
        )
        for canonical_name, aliases in modifier_groups:
            canonical = getattr(keyboard.Key, canonical_name, None)
            if canonical is None:
                continue
            if key == canonical:
                return canonical
            for alias_name in aliases:
                alias = getattr(keyboard.Key, alias_name, None)
                if alias is not None and key == alias:
                    return canonical

        # It's a non-character, non-modifier key.
        return key

    def _on_press(self, key):
        """Callback function for key press events."""
        try:
            if self._hotkeys_suspended:
                self._current_keys.clear()
                self._clear_pending_command()
                return

            normalized_key = self._normalize_key(key)
            # log_text("HOTKEY_DEBUG", f"Key pressed: {key} (Normalized: {normalized_key})")
            self._current_keys.add(normalized_key)

            # --- Check for space bar during dictation ---
            if self._is_dictating and key == keyboard.Key.space:
                # log_text("HOTKEY_DEBUG", "Space bar pressed during dictation. Stopping.")
                self._log_status("Space bar pressed, stopping dictation...", "blue")
                # Trigger the stop command immediately on press
                self._dispatch_hotkey_command(config.COMMAND_STOP_DICTATE)
                # Prevent space from being added to the set if it stops dictation
                self._current_keys.discard(normalized_key)
                return  # Stop further processing for this key press

        except Exception as e:
            print(f"ERROR: Error in _on_press: {e}")
            # log_text("HOTKEY_ERROR", f"Error in _on_press: {e}")

    def _on_release(self, key):
        """Callback function for key release events."""
        try:
            normalized_key = self._normalize_key(key)
            # log_text("HOTKEY_DEBUG", f"Key released: {key} (Normalized: {normalized_key})")

            if self._hotkeys_suspended:
                self._current_keys.discard(normalized_key)
                self._clear_pending_command()
                return

            # Check for combination *before* removing the key
            current_combination = frozenset(self._current_keys)
            # log_text("HOTKEY_DEBUG", f"Current combination: {current_combination}")
            active_hotkeys = self._get_active_hotkey_combinations()
            if (
                self._pending_command is None
                and current_combination in active_hotkeys
            ):
                command = active_hotkeys[current_combination]
                # We detect on first release, but defer execution until all keys are
                # physically released to avoid modifier bleed (e.g., Cmd+Shift still held).
                self._pending_command = command
                self._pending_command_armed_at = time.monotonic()
                self._log_status(
                    f"Hotkey detected on release: {current_combination} -> {command} (pending full key-up)",
                    "blue",
                )

            # Now remove the key
            self._current_keys.discard(normalized_key)
            if self._pending_command:
                pending_age_seconds = time.monotonic() - self._pending_command_armed_at
                if self._current_keys and pending_age_seconds >= self._pending_command_timeout_seconds:
                    self._log_status(
                        "Pending hotkey timed out waiting for key release; dispatching now.",
                        "orange",
                    )
                    self._current_keys.clear()
                    self._dispatch_pending_command_if_ready(force=True)
                else:
                    self._dispatch_pending_command_if_ready()
        except KeyError:
            # Key might have been released that wasn't tracked (e.g., if listener started while key was held)
            # log_text("HOTKEY_DEBUG", f"Key {normalized_key} released but not found in current keys.")
            pass
        except Exception as e:
            print(f"ERROR: Error in _on_release: {e}")
            # log_text("HOTKEY_ERROR", f"Error in _on_release: {e}")

    def _run_listener(self):
        """Runs the pynput listener loop."""
        self._log_status("Hotkey listener thread started.", "grey")
        try:
            # Setup the listener (non-blocking version might be complex with start/stop)
            self._listener = keyboard.Listener(
                on_press=self._on_press, on_release=self._on_release
            )
            self._listener.start()
            # Keep the thread alive until stop_event is set
            self._stop_event.wait()
            self._log_status("Stop event received, stopping listener...", "blue")
            self._listener.stop()
            # Join might be needed here if stop() is not synchronous enough
            self._listener.join()

        except Exception as e:
            self._log_status(f"Error in hotkey listener thread: {e}", "red")
        finally:
            self._listener = None  # Clear listener instance
            self._log_status("Hotkey listener thread finished.", "blue")

    def start(self):
        """Starts the hotkey listener in a separate thread."""
        if not PYNPUT_AVAILABLE:
            self._log_status("Hotkey listener disabled - pynput not available (CI environment)", "orange")
            return
            
        if self._listener_thread is not None and self._listener_thread.is_alive():
            self._log_status("Hotkey listener already running.", "orange")
            return

        self._stop_event.clear()
        self._current_keys.clear()  # Reset keys on start
        self._clear_pending_command()
        self._listener_thread = threading.Thread(
            target=self._run_listener, daemon=False
        )  # Make thread non-daemon
        self._listener_thread.start()

    def stop(self):
        """Stops the hotkey listener thread."""
        if not PYNPUT_AVAILABLE:
            self._log_status("Hotkey listener was disabled - pynput not available", "orange")
            return
            
        if self._listener_thread is None or not self._listener_thread.is_alive():
            self._log_status("Hotkey listener not running.", "orange")
            return

        self._log_status("Attempting to stop hotkey listener...", "blue")
        self._stop_event.set()  # Signal the listener thread to stop

        # Wait for the listener thread to finish
        self._listener_thread.join(timeout=2)  # Add a timeout

        if self._listener_thread.is_alive():
            self._log_status(
                "Hotkey listener thread did not stop gracefully.", "orange"
            )
            # If the listener is stuck, there isn't much more we can do from here
            # without more drastic measures which might be unsafe.
        else:
            self._log_status("Hotkey listener stopped.", "green")

        self._listener_thread = None
        self._current_keys.clear()  # Clear keys on stop
        self._clear_pending_command()

    def get_hotkey_combinations(self):
        return dict(self._get_active_hotkey_combinations())

    def update_shortcut_bindings(self, shortcut_map: dict):
        """
        Update core user-facing shortcut bindings.
        shortcut_map keys:
          - transcribe
          - stopTranscribing
          - retranscribeBackup
        """
        updated = build_default_hotkey_bindings()

        def remove_command_bindings(command_name: str):
            to_remove = [keys for keys, mapped_command in updated.items() if mapped_command == command_name]
            for keys in to_remove:
                del updated[keys]

        # Remove defaults for user-configurable actions before applying new settings.
        for command_name in (
            config.COMMAND_TOGGLE_DICTATE,
            config.COMMAND_STOP_DICTATE,
            config.COMMAND_RETRANSCRIBE_SECONDARY,
        ):
            remove_command_bindings(command_name)

        transcribe_combo = parse_shortcut_to_combo(shortcut_map.get("transcribe", ""))
        stop_combo = parse_shortcut_to_combo(shortcut_map.get("stopTranscribing", ""))
        retranscribe_combo = parse_shortcut_to_combo(shortcut_map.get("retranscribeBackup", ""))

        # If transcribe + stop share the same combo, use toggle behavior.
        if transcribe_combo is not None and stop_combo is not None and transcribe_combo == stop_combo:
            updated[transcribe_combo] = config.COMMAND_TOGGLE_DICTATE
        else:
            if transcribe_combo is not None:
                updated[transcribe_combo] = config.COMMAND_TOGGLE_DICTATE
            if stop_combo is not None:
                updated[stop_combo] = config.COMMAND_STOP_DICTATE

        if retranscribe_combo is not None:
            existing_command = updated.get(retranscribe_combo)
            if existing_command and existing_command != config.COMMAND_RETRANSCRIBE_SECONDARY:
                self._log_status(
                    "Re-transcribe shortcut conflicts with another action; keeping primary action binding.",
                    "orange",
                )
            else:
                updated[retranscribe_combo] = config.COMMAND_RETRANSCRIBE_SECONDARY

        self._hotkey_combinations = updated
        self._log_status("Hotkey bindings updated from settings.", "grey")


# Example Usage (for testing purposes)
if __name__ == "__main__":
    # Make sure config.py is present

    def handle_hotkey_test(command):
        print(f"\n*** Hotkey Executed: Command = {command} ***\n")
        # Example: Stop listener on restart command for testing
        if command == config.COMMAND_RESTART:
            print("Restart command received, stopping listener for test.")
            hotkey_manager.stop()

    def handle_status_update_test(message, color):
        print(f"--- STATUS [{color}]: {message} ---")

    print("Initializing HotkeyManager...")
    hotkey_manager = HotkeyManager(
        on_hotkey_callback=handle_hotkey_test,
        on_status_update_callback=handle_status_update_test,
    )

    print("Starting HotkeyManager...")
    hotkey_manager.start()

    print("\nHotkey listener running. Try pressing hotkeys defined in config.py.")
    print(f"Example: Cmd+Shift+D ({config.COMMAND_START_DICTATE})")
    print(f"Example: Cmd+Shift+R ({config.COMMAND_RESTART}) to stop this test.")
    print("Press Ctrl+C in the console if needed (listener runs as daemon).")

    # Keep the main thread alive while the listener runs
    try:
        while (
            hotkey_manager._listener_thread
            and hotkey_manager._listener_thread.is_alive()
        ):
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nCtrl+C detected. Stopping HotkeyManager...")
        hotkey_manager.stop()

    print("\nHotkeyManager test finished.")
