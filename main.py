# Removed Tkinter imports: tk, messagebox, ThemedTk
import sys
import os
import threading
import json  # For potential structured communication over stdin/stdout
import time
import subprocess
import io
import wave
import uuid
from typing import Any, Dict, Optional

# Make Quartz imports conditional for CI compatibility
try:
    from Quartz.CoreGraphics import (
        CGEventCreateKeyboardEvent,
        CGEventPost,
        kCGHIDEventTap,
        CGEventSetFlags,
        kCGEventFlagMaskCommand,
    )
    QUARTZ_AVAILABLE = True
except ImportError:
    # Quartz not available (CI environment or non-macOS)
    QUARTZ_AVAILABLE = False
    try:
        if not getattr(config, "MINIMAL_TERMINAL_OUTPUT", False):
            print("[WARN] Quartz.CoreGraphics not available - clipboard functionality will be limited")
    except Exception:
        print("[WARN] Quartz.CoreGraphics not available - clipboard functionality will be limited")

# Make pynput imports conditional for CI compatibility
try:
    from pynput import keyboard
    PYNPUT_AVAILABLE = True
except ImportError:
    # pynput not available (CI environment)
    PYNPUT_AVAILABLE = False
    try:
        if not getattr(config, "MINIMAL_TERMINAL_OUTPUT", False):
            print("[WARN] pynput not available - hotkey functionality will be limited")
    except Exception:
        print("[WARN] pynput not available - hotkey functionality will be limited")
    # Create a minimal mock keyboard module for imports
    class MockKeyboard:
        class Key:
            cmd = "cmd"
            cmd_l = "cmd_l" 
            cmd_r = "cmd_r"
            shift = "shift"
            shift_l = "shift_l"
            shift_r = "shift_r"
            ctrl = "ctrl"
            ctrl_l = "ctrl_l"
            ctrl_r = "ctrl_r"
            alt = "alt"
            alt_l = "alt_l"
            alt_gr = "alt_gr"
            space = "space"
            
            def __init__(self, name=None):
                self.name = name
        
        class KeyCode:
            def __init__(self, char=None):
                self.char = char
    
    keyboard = MockKeyboard()

# Optional numpy import for audio serialization
try:
    import numpy as np  # type: ignore
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    np = None  # type: ignore

# Import refactored modules and config
from src.config import config
from src.utils.utils import log_text
from src.audio.audio_handler import AudioHandler
from src.transcription_handler import TranscriptionHandler
from src.hotkey_manager import HotkeyManager
from src.memory_monitor import (
    MemoryMonitor,
    start_memory_monitoring,
    stop_memory_monitoring,
)

import src.memory_monitor as mm_module  # Import with an alias

# Suppress noisy debug path print in minimal terminal mode
try:
    if not getattr(config, "MINIMAL_TERMINAL_OUTPUT", False):
        print(f"[DEBUG_PATH] memory_monitor module loaded from: {mm_module.__file__}")
except Exception:
    pass

# Removed GUI import

# Set environment variable
os.environ["TOKENIZERS_PARALLELISM"] = config.TOKENIZERS_PARALLELISM

from src.config.settings_manager import settings_manager
from src.text_processor import text_processor
from src.history.history_manager import HistoryManager
from src import llm_postprocessor
from src.api_server import LocalAPIServer
from src.dictation_session_store import DictationSessionStore

def _sanitize_for_legacy_clipboards(text: str) -> str:
    """Replace non-breaking hyphens, non-breaking spaces, smart quotes, and narrow no-break spaces.
    Keeps ASCII punctuation to improve compatibility with older apps.
    """
    if not text:
        return text
    replacements = {
        "\u2011": "-",   # non-breaking hyphen → hyphen
        "\u2010": "-",   # hyphen
        "\u2013": "-",   # en dash → hyphen
        "\u2014": "-",   # em dash → hyphen
        "\u00A0": " ",   # non-breaking space → space
        "\u202F": " ",   # narrow no-break space → space
        "\u2009": " ",   # thin space → space
        "\u200A": " ",   # hair space → space
        "\u00AD": "",    # soft hyphen → remove
        "\u2018": "'",   # left single quote → '
        "\u2019": "'",   # right single quote → '
        "\u201C": '"',   # left double quote → "
        "\u201D": '"',   # right double quote → "
        "\u2026": "...", # ellipsis
    }
    out = text
    for k, v in replacements.items():
        out = out.replace(k, v)
    return out


def send_text_to_citrix(text):
    """Copies text to clipboard and simulates Cmd+V."""
    if not text:
        print("No text provided to send.")
        return
    try:
        if getattr(config, "SANITIZE_CLIPBOARD_FOR_LEGACY", True):
            text = _sanitize_for_legacy_clipboards(text)
        # Use pbcopy for clipboard access on macOS
        process = subprocess.Popen(
            "pbcopy", env={"LANG": "en_US.UTF-8"}, stdin=subprocess.PIPE
        )
        process.communicate(input=text.encode("utf-8"))
        print(f"Sent to clipboard: {text[:50]}...")  # Log snippet

        if QUARTZ_AVAILABLE:
            # Simulate Cmd+V using Quartz
            key_code_v = 9  # Keycode for 'v' on macOS
            event_down = CGEventCreateKeyboardEvent(None, key_code_v, True)
            CGEventSetFlags(event_down, kCGEventFlagMaskCommand)
            event_up = CGEventCreateKeyboardEvent(None, key_code_v, False)
            CGEventSetFlags(event_up, kCGEventFlagMaskCommand)

            CGEventPost(kCGHIDEventTap, event_down)
            time.sleep(0.05)  # Small delay between down and up
            CGEventPost(kCGHIDEventTap, event_up)
            print("Simulated Cmd+V")
        else:
            # Fallback: Only copy to clipboard, user needs to paste manually
            print("Text copied to clipboard - Cmd+V simulation not available (Quartz not found)")

    except Exception as e:
        print(f"Error sending text to Citrix: {e}")
        log_text("ERROR", f"Failed to send text via Cmd+V: {e}")


class Application:
    """Main application class orchestrating all components."""

    MAX_SESSION_RESULTS = 50
    SESSION_RESULT_TTL_SECONDS = 15 * 60

    def __init__(self):
        self._program_active = True  # Overall state
        self._current_processing_mode: Optional[str] = None  # Tracks dictation state
        self._last_raw_transcription = ""  # Store last raw text for clipboard
        self._current_dictation_started_at: Optional[float] = None
        self._pending_audio_bytes: Optional[bytes] = None
        self._last_history_entry_id: Optional[str] = None
        self._bg_retranscribe_cancel = threading.Event()
        self._bg_retranscribe_thread: Optional[threading.Thread] = None
        self._bg_retranscribe_result: Optional[Dict[str, Any]] = None
        self.history_manager = HistoryManager()
        self.api_server: Optional[LocalAPIServer] = None
        self._session_store = DictationSessionStore(
            max_results=self.MAX_SESSION_RESULTS,
            ttl_seconds=self.SESSION_RESULT_TTL_SECONDS,
        )

        # --- Initialize Handlers ---
        # Initialize TranscriptionHandler with saved ASR model, coalescing to default if empty/invalid
        saved_asr_model = settings_manager.get_setting("selectedAsrModel", config.DEFAULT_ASR_MODEL)
        if not saved_asr_model:
            saved_asr_model = config.DEFAULT_ASR_MODEL
        self.transcription_handler = TranscriptionHandler(
            on_transcription_complete_callback=self._handle_transcription_complete,
            on_status_update_callback=self._handle_status_update,
            selected_asr_model=saved_asr_model
        )
        self.audio_handler = AudioHandler(
            on_wake_word_callback=self._handle_wake_word,
            on_speech_end_callback=self._handle_speech_end,
            on_status_update_callback=self._handle_status_update,
        )
        self.audio_handler.set_auto_silence_stop_enabled(
            settings_manager.get_setting("autoStopOnSilence", True)
        )
        self.audio_handler.set_wake_word_enabled(
            settings_manager.get_setting("wakeWordEnabled", True)
        )
        self.hotkey_manager = HotkeyManager(
            on_hotkey_callback=self._handle_hotkey,
            on_status_update_callback=self._handle_status_update,
        )

        # --- Initial Setup ---
        self._handle_status_update("Application initializing...", "grey")

    def begin_api_dictation_session(self, *, suppress_paste: bool = False, source: Optional[str] = None) -> str:
        return self._session_store.begin_session(suppress_paste=suppress_paste, source=source)

    def clear_active_session(self, *, as_not_found: bool = False) -> None:
        self._session_store.clear_active(as_not_found=as_not_found)

    def mark_active_session_processing(self) -> Optional[str]:
        return self._session_store.mark_processing()

    def complete_active_session(
        self, *, processed_text: str, history_entry_id: Optional[str], completed_at: Optional[float]
    ) -> Dict[str, Any]:
        return self._session_store.complete_active(
            processed_text=processed_text,
            history_entry_id=history_entry_id,
            completed_at=completed_at,
        )

    def is_stop_session_valid(self, session_id: Optional[str]) -> bool:
        return self._session_store.is_stop_session_valid(session_id)

    def get_status_snapshot(self) -> Dict[str, Any]:
        return self._session_store.get_status_snapshot()

    def get_session_result(self, session_id: str) -> Dict[str, Any]:
        audio_state = None
        try:
            audio_state = self.audio_handler.get_listening_state()
        except Exception:
            audio_state = None
        return self._session_store.get_session_result(session_id, audio_state=audio_state)

    def start_backend(self):
        """Starts the application's background processes (Hotkeys only initially)."""
        self._handle_status_update(
            "Starting background services (Hotkeys only initially)...", "grey"
        )
        
        # Send initial inactive state with grey color to ensure tray starts grey
        initial_state_data = {
            "programActive": False,
            "audioState": "inactive", 
            "isDictating": False,
            "isProofingActive": False,
            "canDictate": False,
            "currentMode": None,
            "wakeWordEnabled": settings_manager.get_setting("wakeWordEnabled", True),
        }
        print(f"STATE:{json.dumps(initial_state_data)}", flush=True)
        
        self.hotkey_manager.start()
        self.start_backend_audio()
        
        # Start Local API
        self.api_server = LocalAPIServer(self)
        self.api_server.start()
        
        # _update_app_state will be called once audio handler is ready

    def start_backend_audio(self):
        """Starts the audio handler. Call this after config is loaded."""
        # Use start_async to avoid blocking main thread during stream opening
        if (
            not self.audio_handler._audio_thread
            or not self.audio_handler._audio_thread.is_alive()
        ):
            self._handle_status_update("Starting Audio Handler (async)...", "grey")
            self.audio_handler.start_async()  # Call the async starter
            
            # Schedule a microphone status check after a brief delay
            threading.Timer(2.0, self._check_microphone_status_delayed).start()

    def _check_microphone_status_delayed(self):
        """
        Checks microphone status after audio handler startup and provides user feedback.
        Called with a delay to allow the audio handler to complete initialization.
        """
        try:
            # If audio handler failed to start properly, get detailed status
            if (not self.audio_handler._program_active and 
                hasattr(self.audio_handler, 'get_microphone_status_message')):
                
                status_message, status_color = self.audio_handler.get_microphone_status_message()
                
                # Only show detailed error suggestions for actual failures (red), not warnings (orange)
                if status_color == "red":
                    self._handle_status_update(status_message, status_color)
                    
                    # Also log the issue for debugging
                    log_text("MIC_STATUS_CHECK", f"Microphone failed: {status_message}")
                    
                    # Send status with action suggestions for serious errors
                    if "permission" in status_message.lower():
                        self._handle_status_update("💡 Check Privacy & Security settings in System Preferences", "blue")
                    elif "no default input" in status_message.lower() or "no input channels" in status_message.lower():
                        self._handle_status_update("💡 Check System Preferences > Sound > Input to select a microphone", "blue")
                    else:
                        self._handle_status_update("💡 Check System Preferences > Sound settings and restart the application", "blue")
                        
                elif status_color == "orange":
                    # For warnings, just log and show basic status
                    log_text("MIC_STATUS_CHECK", f"Microphone warning: {status_message}")
                    # Only show the basic warning message, not additional suggestions
                    self._handle_status_update(status_message, status_color)
                else:
                    # Green status - microphone is working
                    log_text("MIC_STATUS_CHECK", f"Microphone status: {status_message}")
                    
        except Exception as e:
            log_text("MIC_STATUS_CHECK_ERROR", f"Error checking microphone status: {e}")

    def shutdown(self):
        """Shuts down all components gracefully."""
        self._handle_status_update("Shutting down...", "orange")
        try:
            print("SHUTDOWN_SIGNAL", flush=True)  # Signal Electron we are shutting down
            self.hotkey_manager.set_dictating_state(
                False
            )  # Ensure state is false on shutdown
            self.hotkey_manager.stop()
            self.audio_handler.stop()
            if self.api_server:
                self.api_server.stop()
            # Ensure PyAudio is terminated if AudioHandler didn't do it
            if hasattr(self.audio_handler, "_p") and self.audio_handler._p:
                self.audio_handler.terminate_pyaudio()

            # Add any other cleanup needed for TranscriptionHandler if necessary

        except Exception as e:
            log_text("SHUTDOWN_ERROR", f"Error during shutdown: {e}")
            print(f"ERROR: Error during shutdown: {e}", flush=True)
        finally:
            self._handle_status_update("Shutdown complete.", "grey")
            log_text("SHUTDOWN", "Backend shutdown complete.")

    # --- Callback Methods for Handlers ---

    def _handle_status_update(self, message: str, color: str):
        """Receives status updates from handlers and prints them for Electron."""
        # Check if it's an amplitude message and print it directly if so
        if message.startswith("AUDIO_AMP:"):
            try:
                amp_value = int(message.split(":", 1)[1].strip())
            except (ValueError, IndexError):
                amp_value = 0
            self._session_store.set_audio_amp(amp_value)
            print(message, flush=True)
        elif color == "STATE_MSG":
            # This is a detailed STATE JSON message, print it directly
            print(message, flush=True)
            
            # Extract microphone error information if present
            if message.startswith("STATE:"):
                try:
                    state_data = json.loads(message[6:])  # Remove "STATE:" prefix
                    if state_data.get("microphoneError"):
                        # Log the detailed error for debugging
                        log_text("MIC_ERROR_STATE", f"Microphone error: {state_data['microphoneError']}")
                        
                        # Send a user-friendly version to the status display
                        error_msg = state_data["microphoneError"]
                        if len(error_msg) > 80:  # Truncate very long messages
                            error_msg = error_msg[:77] + "..."
                        print(f"STATUS:orange:{error_msg}", flush=True)
                        
                except (json.JSONDecodeError, KeyError) as e:
                    log_text("STATE_PARSE_ERROR", f"Error parsing state message: {e}")
        else:
            # Otherwise, print other status updates with the prefix
            print(f"STATUS:{color}:{message}", flush=True)

    # Removed _process_status_queue method

    def _handle_wake_word(self, command: str):
        """Called by AudioHandler when a wake word is detected."""
        log_text("WAKE_WORD", f"Command received: {command}")

        if not self._program_active:
            self._handle_status_update("Program inactive, wake word ignored.", "orange")
            # Ensure audio handler goes back to activation state if it changed
            self.audio_handler.set_listening_state("activation")
            self._update_app_state()
            return

        if command == config.COMMAND_START_DICTATE:
            # Cancel any in-flight background retranscription
            self._bg_retranscribe_cancel.set()
            self._bg_retranscribe_result = None

            self._current_processing_mode = "dictate"
            self._handle_status_update("Dictation started.", "green")
            self._current_dictation_started_at = time.time()
        else:
            log_text("WAKE_WORD", f"Unknown command from wake word: {command}")
            self.audio_handler.set_listening_state(
                "activation"
            )  # Go back if command invalid
            self._update_app_state()
            return

        # Explicitly set AudioHandler to "dictation" state
        log_text(
            "WAKE_WORD",
            f"Setting AudioHandler state to 'dictation' for command: {command}",
        )
        self.audio_handler.set_listening_state("dictation")
        self.hotkey_manager.set_dictating_state(True)  # <<< SET STATE TO TRUE

        # Update app state (will be printed by _update_app_state)
        log_text(
            "WAKE_WORD", "Updating app state after setting AudioHandler to 'dictation'"
        )
        self._update_app_state()
        # Audio handler should already be in 'dictation' state from its own logic

    def _handle_speech_end(self, audio_data):
        """Called by AudioHandler when speech ends after dictation starts."""
        log_text("SPEECH_END", f"Received {len(audio_data)} audio samples.")
        self._handle_status_update("Speech ended. Transcribing...", "orange")
        self.mark_active_session_processing()
        self._update_app_state()  # Update state to processing

        self._pending_audio_bytes = self._convert_audio_to_wav(audio_data)

        # Ensure the transcription handler uses the up-to-date selected ASR model
        # (If runtime changes happened via CONFIG, model resources are already prepared)
        self.transcription_handler.transcribe_audio_data(
            audio_data, config.DEFAULT_WHISPER_PROMPT
        )

    def _handle_transcription_complete(self, raw_text: str, duration: float):
        """Called by TranscriptionHandler when transcription is complete."""
        log_text(
            "TRANSCRIPTION_COMPLETE",
            f"Duration: {duration:.2f}s, Raw text: {raw_text[:100]}....",
        )

        # Process text if available
        processed_text = raw_text.strip() if raw_text else ""
        
        # Apply text processing (filler word removal, etc.)
        if processed_text:
            # Optional: Enhance with MedGemma LLM if MedASR is selected and feature is enabled
            current_model = getattr(self.transcription_handler, "selected_asr_model", "")
            use_llm_enhancement = settings_manager.get_setting("useMedGemmaPostProcessing", False)
            
            if use_llm_enhancement and current_model == "google/medasr":
                log_text("LLM_ENHANCE", "Enhancing MedASR transcription with MedGemma...")
                enhanced_text = llm_postprocessor.enhance_medical_transcription(processed_text)
                if enhanced_text != processed_text:
                    log_text("LLM_ENHANCE", f"Original: '{processed_text[:80]}...' -> Enhanced: '{enhanced_text[:80]}...'")
                    processed_text = enhanced_text
            
            processed_text = text_processor.clean_text(processed_text)
            
            # Log the processing if any changes were made
            if processed_text != raw_text.strip():
                log_text(
                    "TEXT_PROCESSED",
                    f"Filler words removed. Original: '{raw_text.strip()}' -> Processed: '{processed_text}'",
                )
        
        self._last_raw_transcription = processed_text  # Store processed text

        history_metadata = {
            "model": getattr(self.transcription_handler, "selected_asr_model", None),
            "filterFillerWords": settings_manager.get_setting("filterFillerWords", True)
        }
        history_entry_id = uuid.uuid4().hex
        self._last_history_entry_id = history_entry_id
        history_record = self.history_manager.add_entry(
            entry_id=history_entry_id,
            transcript=raw_text or "",
            processed_transcript=processed_text or "",
            duration_seconds=duration,
            audio_bytes=self._pending_audio_bytes,
            started_at=self._current_dictation_started_at,
            completed_at=time.time(),
            metadata=history_metadata
        )
        self._pending_audio_bytes = None
        self._current_dictation_started_at = None
        session_outcome = self.complete_active_session(
            processed_text=processed_text,
            history_entry_id=history_entry_id,
            completed_at=history_record.get("completedAt"),
        )

        # Send transcription to Electron BEFORE history entry so the frontend
        # finalizes the transcript (status → 'complete') before linking history.
        if processed_text:
            print(f"FINAL_TRANSCRIPT:{processed_text}", flush=True)
            if session_outcome.get("suppressPaste"):
                log_text(
                    "TRANSCRIPTION_COMPLETE",
                    f"Session {session_outcome.get('sessionId')} suppressPaste enabled; skipped clipboard send.",
                )
            else:
                self._handle_status_update("Sending to Citrix...", "blue")
                send_text_to_citrix(processed_text + " ")  # Add space for easier continuation
                log_text("TRANSCRIPTION_COMPLETE", "Text sent to Citrix via clipboard.")
            self._handle_status_update("Transcription complete.", "green")
        else:
            # Empty transcription - always finish
            self._handle_status_update("Transcription returned empty.", "orange")

        # Send history entry AFTER transcript so setLastHistoryEntry() finds the
        # correct (just-finalized) entry when linking.
        print(f"HISTORY_ENTRY:{json.dumps(history_record, ensure_ascii=False)}", flush=True)

        # Reset state and return to listening
        self._current_processing_mode = None
        self.hotkey_manager.set_dictating_state(False)
        self.audio_handler.set_listening_state("activation")
        self._update_app_state()

        # Auto-trigger background retranscription with secondary model if configured
        secondary_model = settings_manager.get_setting("secondaryAsrModel")
        primary_model = getattr(self.transcription_handler, "selected_asr_model", "")
        if secondary_model and secondary_model != primary_model and history_entry_id and processed_text:
            self._start_background_retranscribe(history_entry_id, secondary_model)

    def _convert_audio_to_wav(self, audio_data):
        if audio_data is None:
            return None

        pcm_bytes = None
        try:
            if NUMPY_AVAILABLE and np is not None and isinstance(audio_data, np.ndarray):
                pcm_bytes = audio_data.astype(np.int16, copy=False).tobytes()
        except Exception:
            pcm_bytes = None

        if pcm_bytes is None:
            try:
                if hasattr(audio_data, "tobytes"):
                    pcm_bytes = audio_data.tobytes()
                elif isinstance(audio_data, (bytes, bytearray)):
                    pcm_bytes = bytes(audio_data)
            except Exception:
                pcm_bytes = None

        if not pcm_bytes:
            return None

        buffer = io.BytesIO()
        try:
            with wave.open(buffer, "wb") as wav_file:
                wav_file.setnchannels(config.CHANNELS)
                wav_file.setsampwidth(2)
                wav_file.setframerate(config.SAMPLE_RATE)
                wav_file.writeframes(pcm_bytes)
        except Exception:
            return None

        return buffer.getvalue()

    def _handle_hotkey(self, command: str):
        """Called by HotkeyManager when a hotkey is pressed."""
        log_text("HOTKEY", f"Command received: {command}")

        # --- Handle commands that work regardless of program_active state ---
        if command == config.COMMAND_TOGGLE_ACTIVE:
            self._toggle_program_active()
            return  # State change handled within the method

        if command == config.COMMAND_RESTART:
            self._trigger_restart()
            return

        if command == config.COMMAND_SHOW_HOTKEYS:
            self._send_hotkeys_info()
            return

        # Mini mode toggle is handled by Electron window management
        # Python backend doesn't need to do anything for this command via hotkey
        if command == config.COMMAND_TOGGLE_MINI_MODE:
            log_text("HOTKEY", "Toggle Mini Mode hotkey pressed (handled by frontend).")
            return

        if command == config.COMMAND_RETRANSCRIBE_SECONDARY:
            try:
                self._handle_retranscribe_secondary()
            except Exception as e:
                log_text("RETRANSCRIBE_ERROR", f"Unexpected error in retranscribe handler: {e}")
                print(f"RETRANSCRIBE_START:error:Re-transcribe failed: {e}", flush=True)
                print("RETRANSCRIBE_END:error", flush=True)
                self._handle_status_update(f"Re-transcribe error: {e}", "red")
            return

        # --- Handle commands that only work when program is active ---
        if not self._program_active:
            self._handle_status_update(
                f"Program inactive, hotkey '{command}' ignored.", "orange"
            )
            return

        # Check current audio state before starting new dictation
        current_audio_state = self.audio_handler.get_listening_state()
        if command == config.COMMAND_START_DICTATE:
            log_text("HOTKEY", f"Checking audio state for command: {command}")
            if current_audio_state == "dictation":
                self._handle_status_update(
                    "Already dictating, ignoring start command.", "orange"
                )
                log_text("HOTKEY", "Already dictating, command ignored.")
                return
            if current_audio_state == "processing":
                self._handle_status_update(
                    "Currently processing, ignoring start command.", "orange"
                )
                log_text("HOTKEY", "Currently processing, command ignored.")
                return
            # If in activation, proceed to call _handle_wake_word equivalent
            log_text(
                "HOTKEY",
                f"Audio state is '{current_audio_state}', triggering action for command: {command}",
            )
            self._handle_wake_word(command)  # Simulate wake word detection
            log_text("HOTKEY", f"Called _handle_wake_word with command: {command}")

        elif command == config.COMMAND_STOP_DICTATE:
            if current_audio_state == "dictation":
                self._trigger_stop_dictation()
            else:
                self._handle_status_update(
                    "Not dictating, stop command ignored.", "orange"
                )

        # Add handling for ABORT hotkey if defined in config
        elif (
            command == config.COMMAND_ABORT_DICTATE
        ):  # Assuming you define this in config.py
            if current_audio_state in ["dictation", "processing"]:
                self._trigger_abort_dictation()
            else:
                self._handle_status_update(
                    "Not dictating/processing, abort command ignored.", "orange"
                )

        else:
            log_text("HOTKEY", f"Unhandled hotkey command: {command}")

    def _handle_retranscribe_secondary(self):
        """Re-transcribe the most recent dictation with the secondary ASR model.

        If a background retranscription has already completed, use the cached result
        immediately instead of re-running the model.
        """
        secondary_model = settings_manager.get_setting("secondaryAsrModel")
        if not secondary_model:
            print("RETRANSCRIBE_START:error:No secondary ASR model configured. Set one in Settings.", flush=True)
            print("RETRANSCRIBE_END:error", flush=True)
            self._handle_status_update("No secondary ASR model configured. Set one in Settings.", "orange")
            return

        # Check if background retranscription already has a cached result
        cached = self._bg_retranscribe_result
        if cached and cached.get("success") and cached.get("transcript"):
            cached_entry_id = cached.get("entryId")
            if (
                cached_entry_id
                and self._last_history_entry_id
                and cached_entry_id != self._last_history_entry_id
            ):
                log_text(
                    "RETRANSCRIBE",
                    f"Ignoring stale cached result for {cached_entry_id}; latest is {self._last_history_entry_id}",
                )
                self._bg_retranscribe_result = None
            else:
                log_text("RETRANSCRIBE", "Using cached background retranscribe result")
                result_text = cached["transcript"]
                print(f"RETRANSCRIBE_START:{cached.get('modelId', secondary_model)}", flush=True)
                print("RETRANSCRIBE_END:success", flush=True)
                # Re-emit as a manual result so frontend updates the linked transcript entry.
                manual_payload = dict(cached)
                manual_payload["autoTriggered"] = False
                print(f"RETRANSCRIBE_QUICK_RESULT:{json.dumps(manual_payload, ensure_ascii=False)}", flush=True)
                send_text_to_citrix(result_text + " ")
                self._handle_status_update("Re-transcription complete (cached).", "green")
                self._bg_retranscribe_result = None
                return

        entry_id = self._last_history_entry_id
        if not entry_id:
            print("RETRANSCRIBE_START:error:No recent dictation to re-transcribe.", flush=True)
            print("RETRANSCRIBE_END:error", flush=True)
            self._handle_status_update("No recent dictation to re-transcribe.", "orange")
            return

        audio_path = os.path.join("data", "history", "audio", f"{entry_id}.wav")
        if not os.path.exists(audio_path):
            print("RETRANSCRIBE_START:error:Audio file not found for last dictation.", flush=True)
            print("RETRANSCRIBE_END:error", flush=True)
            self._handle_status_update("Audio file not found for last dictation.", "orange")
            return

        print(f"RETRANSCRIBE_START:{secondary_model}", flush=True)
        self._handle_status_update(f"Re-transcribing with {secondary_model}...", "blue")

        def retranscribe_worker():
            try:
                start_time = time.time()
                result_text = self.transcription_handler.retranscribe_audio_file(audio_path, secondary_model)

                if result_text:
                    use_llm = settings_manager.get_setting("useMedGemmaPostProcessing", False)
                    if use_llm and secondary_model == "google/medasr":
                        result_text = llm_postprocessor.enhance_medical_transcription(result_text)
                    result_text = text_processor.clean_text(result_text)

                duration = time.time() - start_time

                result_payload = {
                    "success": True,
                    "entryId": entry_id,
                    "modelId": secondary_model,
                    "transcript": result_text or "",
                    "duration": round(duration, 2)
                }
                print("RETRANSCRIBE_END:success", flush=True)
                print(f"RETRANSCRIBE_QUICK_RESULT:{json.dumps(result_payload, ensure_ascii=False)}", flush=True)

                if result_text:
                    send_text_to_citrix(result_text + " ")
                    self._handle_status_update("Re-transcription complete.", "green")
                else:
                    self._handle_status_update("Re-transcription returned empty.", "orange")

            except Exception as e:
                log_text("RETRANSCRIBE_ERROR", f"Quick retranscribe failed: {e}")
                error_payload = {
                    "success": False,
                    "entryId": entry_id,
                    "modelId": secondary_model,
                    "error": str(e)
                }
                print("RETRANSCRIBE_END:error", flush=True)
                print(f"RETRANSCRIBE_QUICK_RESULT:{json.dumps(error_payload)}", flush=True)
                self._handle_status_update(f"Re-transcription failed: {e}", "red")

        threading.Thread(target=retranscribe_worker, daemon=True).start()

    def _start_background_retranscribe(self, entry_id: str, secondary_model: str):
        """Spawn a background thread to retranscribe with the secondary model."""
        # Cancel any prior in-flight background job
        self._bg_retranscribe_cancel.set()
        self._bg_retranscribe_result = None

        # Clear the event for the new job
        self._bg_retranscribe_cancel = threading.Event()
        cancel_event = self._bg_retranscribe_cancel

        audio_path = os.path.join("data", "history", "audio", f"{entry_id}.wav")
        if not os.path.exists(audio_path):
            log_text("BG_RETRANSCRIBE", f"Audio file not found, skipping background retranscribe: {audio_path}")
            return

        def bg_worker():
            try:
                if cancel_event.is_set():
                    return

                log_text("BG_RETRANSCRIBE", f"Starting background retranscribe with {secondary_model}")
                start_time = time.time()
                result_text = self.transcription_handler.retranscribe_audio_file(audio_path, secondary_model)

                if cancel_event.is_set():
                    log_text("BG_RETRANSCRIBE", "Cancelled after transcription completed")
                    return

                if result_text:
                    use_llm = settings_manager.get_setting("useMedGemmaPostProcessing", False)
                    if use_llm and secondary_model == "google/medasr":
                        result_text = llm_postprocessor.enhance_medical_transcription(result_text)
                    result_text = text_processor.clean_text(result_text)

                duration = time.time() - start_time

                if cancel_event.is_set():
                    return

                result_payload = {
                    "success": True,
                    "entryId": entry_id,
                    "modelId": secondary_model,
                    "transcript": result_text or "",
                    "duration": round(duration, 2),
                    "autoTriggered": True
                }

                # Cache the result so Cmd+Shift+X can use it immediately
                self._bg_retranscribe_result = result_payload

                print(f"RETRANSCRIBE_QUICK_RESULT:{json.dumps(result_payload, ensure_ascii=False)}", flush=True)
                log_text("BG_RETRANSCRIBE", f"Background retranscribe complete in {duration:.2f}s")

            except Exception as e:
                if cancel_event.is_set():
                    return
                log_text("BG_RETRANSCRIBE_ERROR", f"Background retranscribe failed: {e}")
                error_payload = {
                    "success": False,
                    "entryId": entry_id,
                    "modelId": secondary_model,
                    "error": str(e),
                    "autoTriggered": True
                }
                print(f"RETRANSCRIBE_QUICK_RESULT:{json.dumps(error_payload)}", flush=True)

        thread = threading.Thread(target=bg_worker, daemon=True)
        self._bg_retranscribe_thread = thread
        thread.start()

    # --- Command Handling Methods (Triggered by stdin) ---

    def _trigger_stop_dictation(self):
        """Handles stop dictation command (process audio) from Electron or hotkey."""
        log_text("COMMAND", "Stop Dictation (Process) requested.")
        current_audio_state = (
            self.audio_handler.get_listening_state()
        )  # Get state before
        log_text(
            "DEBUG",
            f"Before force_process_audio, AudioHandler state: {current_audio_state}",
        )

        if current_audio_state == "dictation":
            self._handle_status_update(
                "Stopping dictation manually & processing...", "orange"
            )
            self.mark_active_session_processing()
            self.audio_handler.force_process_audio()
            new_audio_state = (
                self.audio_handler.get_listening_state()
            )  # Get state after
            log_text(
                "DEBUG",
                f"After force_process_audio, AudioHandler state: {new_audio_state}",
            )
            # State update will happen implicitly via the callbacks triggered by force_process_audio
        else:
            self._handle_status_update(
                f"Not currently dictating (state: {current_audio_state}), stop command ignored.",
                "orange",
            )
            log_text(
                "DEBUG",
                f"Stop command ignored, AudioHandler state: {current_audio_state}",
            )

    def _trigger_abort_dictation(self):
        """Handles abort dictation command (discard audio) from Electron or hotkey."""
        log_text("COMMAND", "Abort Dictation (Discard) requested.")
        self.audio_handler.abort_dictation()  # Call the new method in AudioHandler
        self.hotkey_manager.set_dictating_state(False)  # <<< SET STATE TO FALSE
        self._pending_audio_bytes = None
        self._current_dictation_started_at = None
        self.clear_active_session(as_not_found=True)
        self._update_app_state()  # Update state after aborting

    def _trigger_restart(self):
        """Handles restart command from Electron or hotkey."""
        # Confirmation should be handled in Electron frontend if desired
        log_text("COMMAND", "Restart requested.")
        self.shutdown()
        # Use os.execv to replace the current process with a new instance
        try:
            python = sys.executable
            os.execl(python, python, *sys.argv)
        except Exception as e:
            log_text("RESTART_ERROR", f"Failed to restart application: {e}")
            print(f"ERROR: Failed to restart application: {e}", flush=True)
            # Attempt to exit normally if exec fails
            sys.exit(1)

    def _send_hotkeys_info(self):
        """Sends hotkey information to Electron."""
        log_text("COMMAND", "Get Hotkeys requested.")
        # Send hotkeys as a structured message (e.g., JSON)
        hotkey_data = {}
        for combo, command in config.HOTKEY_COMBINATIONS.items():
            keys_str_list = []
            for key in combo:
                if isinstance(key, keyboard.KeyCode):
                    char = getattr(key, "char", "?")
                    keys_str_list.append(char)
                elif isinstance(key, keyboard.Key):
                    key_map = {
                        keyboard.Key.cmd: "Cmd",
                        keyboard.Key.cmd_l: "Cmd",
                        keyboard.Key.cmd_r: "Cmd",
                        keyboard.Key.shift: "Shift",
                        keyboard.Key.shift_l: "Shift",
                        keyboard.Key.shift_r: "Shift",
                        keyboard.Key.ctrl: "Ctrl",
                        keyboard.Key.ctrl_l: "Ctrl",
                        keyboard.Key.ctrl_r: "Ctrl",
                        keyboard.Key.alt: "Alt",
                        keyboard.Key.alt_l: "Alt",
                        keyboard.Key.alt_gr: "AltGr",
                        keyboard.Key.space: "Space",
                    }
                    keys_str_list.append(key_map.get(key, key.name))
            keys_str_list.sort(
                key=lambda x: 0 if x in ["Cmd", "Shift", "Ctrl", "Alt"] else 1
            )
            combo_str = "+".join(keys_str_list)
            hotkey_data[combo_str] = command

        print(f"HOTKEYS:{json.dumps(hotkey_data)}", flush=True)

    # Mini mode toggle is handled entirely by Electron, no backend action needed

    # --- State Management ---

    def _toggle_program_active(self):
        """Toggles the overall program active state."""
        self._program_active = not self._program_active
        log_text("STATE_CHANGE", f"Program active set to: {self._program_active}")
        # Inform the audio handler
        self.audio_handler.set_program_active(self._program_active)
        if not self._program_active:
            self.hotkey_manager.set_dictating_state(
                False
            )  # <<< SET STATE TO FALSE if program deactivated
        # Send state update to Electron
        self._update_app_state()

    def _send_ipc_to_electron(self, channel: str, payload: dict = None):
        """Sends a structured IPC message to Electron via stdout."""
        try:
            message = f"IPC_MESSAGE:{channel}:{json.dumps(payload) if payload else ''}"
            print(message, flush=True)
            log_text(
                "IPC_SEND",
                f"Sent to Electron: {channel}, Payload: {str(payload)[:100]}...",
            )
        except Exception as e:
            log_text(
                "IPC_SEND_ERROR",
                f"Error sending IPC message {channel} to Electron: {e}",
            )

    def _update_app_state(self):
        """Determines current state and sends it to Electron."""
        audio_state = self.audio_handler.get_listening_state()
        is_dictating = audio_state == "dictation"
        # Use the AudioHandler's program active state since it knows if microphone is available
        audio_handler_active = self.audio_handler._program_active
        wake_word_enabled = self.audio_handler.is_wake_word_enabled()
        can_dictate = audio_handler_active and audio_state == "activation" and wake_word_enabled

        state_data = {
            "programActive": audio_handler_active,  # Use AudioHandler's state instead of self._program_active
            "audioState": audio_state,  # "activation", "dictation", "processing"
            "isDictating": is_dictating,
            "canDictate": can_dictate,
            "currentMode": self._current_processing_mode,  # 'dictate' or None
            "wakeWordEnabled": wake_word_enabled,
        }
        print(f"STATE:{json.dumps(state_data)}", flush=True)

        # Also send a user-friendly status message based on state
        if not audio_handler_active:
            status_text = "Microphone not available (Hotkeys still work)"
            status_color = "orange"
        elif audio_state == "activation":
            if wake_word_enabled:
                status_text = "Listening for activation words..."
                status_color = "blue"
            else:
                status_text = "Wake word detection off (use shortcuts or manual start)"
                status_color = "grey"
        elif audio_state == "dictation":
            status_text = "Listening for dictation..."
            status_color = "green"
        elif audio_state == "processing":
            status_text = "Processing audio..."
            status_color = "orange"
        else:
            status_text = "Unknown state"
            status_color = "red"

        self._handle_status_update(
            status_text, status_color
        )  # This now prints STATUS:color:message


# --- Main Execution ---
if __name__ == "__main__":
    app = None  # Initialize app to None
    try:
        log_text("STARTUP", "Backend application starting...")
        app = Application()
        app.start_backend()  # Start audio, hotkeys

        log_text("STARTUP", "Backend ready. Listening for commands on stdin...")
        print(
            "PYTHON_BACKEND_READY", flush=True
        )  # Signal Electron that backend is ready
        sys.stdout.flush()  # Explicit flush

        # Request configuration from Electron after signaling readiness
        log_text("STARTUP_TRACE", "About to send GET_CONFIG request.")  # ADDED TRACE
        log_text("CONFIG", "Sending GET_CONFIG request to Electron...")
        print("GET_CONFIG", flush=True)
        sys.stdout.flush()  # Explicit flush
        config_loaded = False
        received_config = None

        # Main loop to read commands from stdin
        for line in sys.stdin:
            command_line = line.strip()
            log_text("STDIN", f"Received command: {command_line}")
            # --- CONFIGURATION HANDLING ---
            if command_line.startswith("CONFIG:"):  # Changed command check
                log_text("STARTUP_TRACE", "Received CONFIG: command.")  # Updated TRACE
                config_str = command_line[
                    len("CONFIG:") :
                ]  # Extract JSON from the same line
                try:
                    received_config = json.loads(config_str)
                    # Removed call to non-existent config.load_settings_from_json
                    config_loaded = True
                    log_text("CONFIG", "Configuration received from Electron.")
                    log_text(
                        "STARTUP_TRACE",
                        f"Successfully parsed config JSON: {received_config}",
                    )  # ADDED TRACE

                    # --- Directly update handlers from received_config ---
                    if "wakeWords" in received_config:
                        app.audio_handler.update_wake_words(
                            received_config["wakeWords"]
                        )
                        # Save wake words to persistent settings
                        settings_manager.set_setting("wakeWords", received_config["wakeWords"], save=False)
                    else:
                        log_text(
                            "CONFIG_WARN", "Wake words not found in received config."
                        )

                    if "selectedAsrModel" in received_config:
                        try:
                            app.transcription_handler.update_selected_asr_model(
                                received_config["selectedAsrModel"]
                            )
                            settings_manager.set_setting(
                                "selectedAsrModel",
                                received_config["selectedAsrModel"],
                                save=False,
                            )
                            log_text(
                                "CONFIG",
                                f"ASR model set to: {received_config['selectedAsrModel']}",
                            )
                        except Exception as e:
                            log_text("CONFIG_ERROR", f"Failed to update ASR model: {e}")
                    else:
                        log_text(
                            "CONFIG_WARN",
                            "selectedAsrModel not found in received config.",
                        )

                    if "fillerWords" in received_config:
                        text_processor.set_filler_words(received_config["fillerWords"])
                        log_text("CONFIG", f"Filler words updated: {received_config['fillerWords']}")

                    if "autoStopOnSilence" in received_config:
                        auto_stop = bool(received_config["autoStopOnSilence"])
                        settings_manager.set_setting("autoStopOnSilence", auto_stop, save=False)
                        app.audio_handler.set_auto_silence_stop_enabled(auto_stop)
                        log_text("CONFIG", f"Auto-stop on silence set to {auto_stop}")

                    if "wakeWordEnabled" in received_config:
                        wake_word_enabled = bool(received_config["wakeWordEnabled"])
                        settings_manager.set_setting("wakeWordEnabled", wake_word_enabled, save=False)
                        app.audio_handler.set_wake_word_enabled(wake_word_enabled)
                        log_text("CONFIG", f"Wake word listening enabled: {wake_word_enabled}")

                    if "secondaryAsrModel" in received_config:
                        settings_manager.set_setting("secondaryAsrModel", received_config["secondaryAsrModel"], save=False)
                        log_text("CONFIG", f"Secondary ASR model set to: {received_config['secondaryAsrModel']}")

                    # Save all settings to file
                    settings_manager.save_settings()
                    # --- End direct updates ---

                    app._handle_status_update(
                        "Configuration applied.", "grey"
                    )  # Changed status message
                    app._update_app_state()  # Reflect state change to Electron

                except json.JSONDecodeError as e:
                    log_text("CONFIG_ERROR", f"JSON decode error on config: {e}")
                    app._handle_status_update(f"Config JSON error: {e}", "red")

            elif command_line == "STOP_DICTATION":
                app._trigger_stop_dictation()

            elif command_line == "ABORT_DICTATION":
                app._trigger_abort_dictation()

            elif command_line == "GET_HOTKEYS":
                app._send_hotkeys_info()

            elif command_line == "TOGGLE_ACTIVE":
                app._toggle_program_active()

            elif command_line == "RESTART_APP":
                app._trigger_restart()

            elif command_line.startswith("SET_APP_STATE:"):
                try:
                    active_status = command_line[len("SET_APP_STATE:") :]
                    active = active_status.lower() == "true"
                    app.audio_handler.set_program_active(active)
                    app._program_active = active  # Update internal state too
                    log_text(
                        "COMMAND", f"Set program active state via command: {active}"
                    )
                    app._update_app_state()  # Reflect state change to Electron
                except ValueError:
                    log_text(
                        "COMMAND_ERROR",
                        f"Invalid active state command format: {command_line}",
                    )
                    app._handle_status_update("Invalid state command.", "red")

            elif command_line.startswith("VOCABULARY_API:"):
                # Handle vocabulary API commands
                try:
                    # Parse the vocabulary command: VOCABULARY_API:messageId:{"command": "...", "data": {...}}
                    parts = command_line.split(":", 2)
                    if len(parts) >= 3:
                        message_id = parts[1]
                        command_data = json.loads(parts[2])
                        
                        # Import and call vocabulary API
                        from src.vocabulary.vocabulary_api import handle_vocabulary_command
                        result = handle_vocabulary_command(
                            command_data.get("command", ""),
                            **command_data.get("data", {})
                        )
                        
                        # Send response back to Electron
                        response_message = f"VOCAB_RESPONSE:{message_id}:{json.dumps(result)}"
                        print(response_message, flush=True)
                        sys.stdout.flush()
                        
                        log_text("VOCAB_API", f"Handled vocabulary command: {command_data.get('command')} - Success: {result.get('success')}")
                    else:
                        log_text("VOCAB_ERROR", f"Invalid vocabulary API command format: {command_line}")
                        
                except json.JSONDecodeError as e:
                    log_text("VOCAB_ERROR", f"JSON decode error in vocabulary API: {e}")
                except Exception as e:
                    log_text("VOCAB_ERROR", f"Error handling vocabulary API: {e}")
                    # Send error response
                    if 'message_id' in locals():
                        error_response = f"VOCAB_RESPONSE:{message_id}:{json.dumps({'success': False, 'error': str(e)})}"
                        print(error_response, flush=True)
                        sys.stdout.flush()

            elif command_line.startswith("ENSURE_MODEL:"):
                parts = command_line.split(":", 2)
                if len(parts) < 3:
                    log_text("COMMAND_ERROR", f"Invalid ENSURE_MODEL command: {command_line}")
                    continue
                request_id = parts[1]
                repo_id = parts[2]
                if repo_id.lower().startswith("apple:"):
                    # Verify helper app exists (dev or bundled).
                    helper_candidates = [
                        os.path.abspath(config.resolve_resource_path("AppleSpeechHelper.app")),
                        os.path.abspath(os.path.join(os.path.dirname(__file__), "tools", "apple_speech_helper", "dist", "AppleSpeechHelper.app")),
                    ]
                    helper_path = next((p for p in helper_candidates if os.path.isdir(p) and p.lower().endswith(".app")), None)
                    if not helper_path:
                        error_payload = {
                            "success": False,
                            "modelId": repo_id,
                            "error": "AppleSpeechHelper.app not found. Build it with: bash tools/apple_speech_helper/build.sh"
                        }
                        print(f"MODEL_ERROR:{request_id}:{json.dumps(error_payload)}", flush=True)
                        sys.stdout.flush()
                        log_text("COMMAND_ERROR", f"Apple model selected but helper missing: {repo_id}")
                        continue
                    response = {
                        "success": True,
                        "modelId": repo_id,
                        "localPath": helper_path,
                        "message": "Apple Speech selected (helper found; no model download required)."
                    }
                    print(f"MODEL_READY:{request_id}:{json.dumps(response)}", flush=True)
                    sys.stdout.flush()
                    log_text("COMMAND", f"No-op ensure for Apple model: {repo_id}")
                    continue
                try:
                    local_path = app.transcription_handler.ensure_model_assets(repo_id)
                    response = {
                        "success": True,
                        "modelId": repo_id,
                        "localPath": local_path,
                        "message": "Model assets ready."
                    }
                    print(f"MODEL_READY:{request_id}:{json.dumps(response)}", flush=True)
                    sys.stdout.flush()
                    log_text("COMMAND", f"Model assets ensured for {repo_id}")
                except Exception as ensure_err:
                    error_payload = {
                        "success": False,
                        "modelId": repo_id,
                        "error": str(ensure_err)
                    }
                    print(f"MODEL_ERROR:{request_id}:{json.dumps(error_payload)}", flush=True)
                    sys.stdout.flush()
                    log_text("COMMAND_ERROR", f"Failed to ensure model {repo_id}: {ensure_err}")

            elif command_line.startswith("REPASTE:"):
                repaste_text = command_line[len("REPASTE:"):]
                if repaste_text:
                    log_text("REPASTE", f"Re-pasting text: {repaste_text[:50]}...")
                    send_text_to_citrix(repaste_text + " ")
                else:
                    log_text("REPASTE", "Empty repaste text, ignoring.")

            elif command_line == "start_dictate":
                app._handle_hotkey(config.COMMAND_START_DICTATE)

            elif command_line == "MODELS_REQUEST":
                # Send available models list to Electron
                models_payload = json.dumps(config.AVAILABLE_ASR_MODELS)
                print(f"MODELS_LIST:{models_payload}", flush=True)
                sys.stdout.flush()
                log_text("COMMAND", "Sent MODELS_LIST to Electron")

            elif command_line.startswith("RETRANSCRIBE_AUDIO:"):
                # Handle re-transcription request: RETRANSCRIBE_AUDIO:<requestId>:<entryId>:<modelId>
                try:
                    parts = command_line.split(":", 3)
                    if len(parts) < 4:
                        log_text("RETRANSCRIBE_ERROR", f"Invalid RETRANSCRIBE_AUDIO format: {command_line}")
                        continue
                    
                    request_id = parts[1]
                    entry_id = parts[2]
                    model_id = parts[3]
                    
                    log_text("RETRANSCRIBE", f"Starting retranscription: entry={entry_id}, model={model_id}")
                    
                    # Load audio file from history
                    audio_path = os.path.join("data", "history", "audio", f"{entry_id}.wav")
                    if not os.path.exists(audio_path):
                        error_payload = {
                            "success": False,
                            "error": f"Audio file not found: {audio_path}"
                        }
                        print(f"RETRANSCRIBE_RESULT:{request_id}:{json.dumps(error_payload)}", flush=True)
                        sys.stdout.flush()
                        continue
                    
                    # Create a temporary transcription handler with the specified model
                    import time
                    start_time = time.time()
                    
                    # Use the existing transcription handler's retranscribe method
                    result_text = app.transcription_handler.retranscribe_audio_file(audio_path, model_id)
                    
                    # Apply filler word removal (same as live transcription)
                    if result_text:
                        # Optional: Enhance with MedGemma LLM if MedASR is used
                        use_llm_enhancement = settings_manager.get_setting("useMedGemmaPostProcessing", False)
                        if use_llm_enhancement and model_id == "google/medasr":
                            log_text("LLM_ENHANCE", "Enhancing retranscription with MedGemma...")
                            result_text = llm_postprocessor.enhance_medical_transcription(result_text)
                        
                        result_text = text_processor.clean_text(result_text)
                    
                    duration = time.time() - start_time
                    
                    response = {
                        "success": True,
                        "entryId": entry_id,
                        "modelId": model_id,
                        "transcript": result_text,
                        "duration": round(duration, 2)
                    }
                    print(f"RETRANSCRIBE_RESULT:{request_id}:{json.dumps(response)}", flush=True)
                    sys.stdout.flush()
                    log_text("RETRANSCRIBE", f"Completed retranscription in {duration:.2f}s")
                    
                except Exception as retrans_err:
                    log_text("RETRANSCRIBE_ERROR", f"Retranscription failed: {retrans_err}")
                    error_payload = {
                        "success": False,
                        "error": str(retrans_err)
                    }
                    if 'request_id' in locals():
                        print(f"RETRANSCRIBE_RESULT:{request_id}:{json.dumps(error_payload)}", flush=True)
                        sys.stdout.flush()

            elif command_line == "SHUTDOWN":
                log_text("COMMAND", "Shutdown command received from Electron.")
                # app.shutdown() # Shutdown is handled in finally block
                break  # Exit the loop and end the backend process

            else:
                log_text("COMMAND_UNKNOWN", f"Unknown command received: {command_line}")
                print(
                    f"UNKNOWN_COMMAND:{command_line}", flush=True
                )  # For debugging in Electron
                sys.stdout.flush()  # Explicit flush

    except BrokenPipeError:
        log_text("PIPE_ERROR", "Broken pipe error (Electron likely closed). Exiting.")
    except Exception as e:
        # Log the exception that occurred during startup or main loop
        log_text(
            "CRITICAL_ERROR", f"Unhandled exception: {e}"
        )  # Add exc_info for traceback
        print(
            f"ERROR: CRITICAL - {e}", flush=True
        )  # Also print basic error for Electron
        sys.stdout.flush()  # Explicit flush
    finally:
        log_text("SHUTDOWN", "Main loop finished or error occurred.")
        if app:  # Check if app was successfully initialized before trying to shut down
            try:
                app.shutdown()
            except Exception as shutdown_e:
                log_text(
                    "SHUTDOWN_ERROR",
                    f"Error during final shutdown: {shutdown_e}",
                    exc_info=True,
                )
                print(f"ERROR: Shutdown error - {shutdown_e}", flush=True)
                sys.stdout.flush()  # Explicit flush
        else:
            log_text(
                "SHUTDOWN", "App object was not initialized, skipping shutdown call."
            )
        print(
            "BACKEND_SHUTDOWN_FINALIZED", flush=True
        )  # Last signal to Electron on hard exit
        sys.stdout.flush()  # Explicit flush
