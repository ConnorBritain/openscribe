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
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

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
from src.utils.utils import log_event, log_text
from src.audio.audio_handler import AudioHandler
from src.transcription_handler import TranscriptionHandler
from src.secondary_asr_worker import SecondaryAsrWorkerClient
from src.hotkey_manager import HotkeyManager
from src import ipc_contract
from src.dictation_lifecycle import DictationLifecycleStateMachine
from src.text_insertion.safe_text_inserter import SafeTextInserter
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
from src.vocabulary.medication_autolearn import (
    MedicationAutoLearnService,
    set_global_medication_autolearn_service,
)
from src.vocabulary.vocabulary_api import VocabularyAPI

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
        self._secondary_worker_enabled = True
        self._secondary_asr_worker: Optional[SecondaryAsrWorkerClient] = None
        timeout_raw = os.getenv("CT_SECONDARY_ASR_TIMEOUT_SECONDS", "240").strip()
        try:
            self._secondary_worker_timeout_seconds = max(30.0, float(timeout_raw))
        except ValueError:
            self._secondary_worker_timeout_seconds = 240.0
        self.history_manager = HistoryManager()
        self.api_server: Optional[LocalAPIServer] = None
        self._session_store = DictationSessionStore(
            max_results=self.MAX_SESSION_RESULTS,
            ttl_seconds=self.SESSION_RESULT_TTL_SECONDS,
        )
        self._lifecycle = DictationLifecycleStateMachine(initial_state="idle")
        self._text_inserter = SafeTextInserter(
            paste_callback=send_text_to_citrix,
            status_callback=self._handle_status_update,
            log_callback=log_text,
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
        self._apply_hotkey_settings_from_store()
        self.medication_autolearn_service = MedicationAutoLearnService(
            settings_enabled_getter=lambda: settings_manager.get_setting("medicationAutoLearnEnabled", True),
            busy_check=self._is_dictation_or_processing_active,
            on_run_complete=self._handle_medication_autolearn_summary,
            state_path="data/medication_autolearn_state.json",
            history_path=self.history_manager.history_log,
            lexicon_path="data/medical_lexicon.json",
            user_vocabulary_path=str(Path("data/user_vocabulary.json")),
        )
        self.medication_autolearn_service.set_runtime_enabled(
            bool(settings_manager.get_setting("medicationAutoLearnEnabled", True))
        )
        set_global_medication_autolearn_service(self.medication_autolearn_service)
        self.vocabulary_api = VocabularyAPI()
        self.vocabulary_api.set_medication_autolearn_service(self.medication_autolearn_service)
        self._stdin_exact_handlers: Dict[str, Callable[[str], bool]] = {}
        self._stdin_prefix_handlers: Tuple[Tuple[str, Callable[[str], bool]], ...] = ()
        self._initialize_stdin_dispatch()

        # --- Initial Setup ---
        self._handle_status_update("Application initializing...", "grey")

    def begin_api_dictation_session(self, *, suppress_paste: bool = False, source: Optional[str] = None) -> str:
        return self._session_store.begin_session(suppress_paste=suppress_paste, source=source)

    def _build_shortcut_settings_payload(self, config_data: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        source = config_data or {}
        return {
            "transcribe": str(source.get("transcribeShortcut") or settings_manager.get_setting("transcribeShortcut", "Option+Space")),
            "stopTranscribing": str(source.get("stopTranscribingShortcut") or settings_manager.get_setting("stopTranscribingShortcut", "Cmd+Shift+S")),
            "retranscribeBackup": str(source.get("retranscribeBackupShortcut") or settings_manager.get_setting("retranscribeBackupShortcut", "Ctrl+Option+R")),
        }

    def _apply_hotkey_settings_from_store(self, config_data: Optional[Dict[str, Any]] = None) -> None:
        try:
            shortcut_payload = self._build_shortcut_settings_payload(config_data)
            self.hotkey_manager.update_shortcut_bindings(shortcut_payload)
        except Exception as error:
            log_text("HOTKEY_CONFIG", f"Failed to apply hotkey settings: {error}")

    def apply_runtime_config(self, received_config: Dict[str, Any]) -> None:
        """Apply CONFIG payload updates from Electron and persist settings."""
        if "wakeWords" in received_config:
            self.audio_handler.update_wake_words(received_config["wakeWords"])
            settings_manager.set_setting("wakeWords", received_config["wakeWords"], save=False)
        else:
            log_text("CONFIG_WARN", "Wake words not found in received config.")

        if "selectedAsrModel" in received_config:
            try:
                self.transcription_handler.update_selected_asr_model(received_config["selectedAsrModel"])
                settings_manager.set_setting(
                    "selectedAsrModel",
                    received_config["selectedAsrModel"],
                    save=False,
                )
                log_text("CONFIG", f"ASR model set to: {received_config['selectedAsrModel']}")
            except Exception as e:
                log_text("CONFIG_ERROR", f"Failed to update ASR model: {e}")
        else:
            log_text("CONFIG_WARN", "selectedAsrModel not found in received config.")

        if "fillerWords" in received_config:
            text_processor.set_filler_words(received_config["fillerWords"])
            log_text("CONFIG", f"Filler words updated: {received_config['fillerWords']}")

        if "autoStopOnSilence" in received_config:
            auto_stop = bool(received_config["autoStopOnSilence"])
            settings_manager.set_setting("autoStopOnSilence", auto_stop, save=False)
            self.audio_handler.set_auto_silence_stop_enabled(auto_stop)
            log_text("CONFIG", f"Auto-stop on silence set to {auto_stop}")

        if "wakeWordEnabled" in received_config:
            wake_word_enabled = bool(received_config["wakeWordEnabled"])
            settings_manager.set_setting("wakeWordEnabled", wake_word_enabled, save=False)
            self.audio_handler.set_wake_word_enabled(wake_word_enabled)
            log_text("CONFIG", f"Wake word listening enabled: {wake_word_enabled}")

        if "medicationAutoLearnEnabled" in received_config:
            auto_learn_enabled = bool(received_config["medicationAutoLearnEnabled"])
            settings_manager.set_setting("medicationAutoLearnEnabled", auto_learn_enabled, save=False)
            self.medication_autolearn_service.set_runtime_enabled(auto_learn_enabled)
            log_text("CONFIG", f"Medication auto-learn enabled: {auto_learn_enabled}")

        if "secondaryAsrModel" in received_config:
            raw_secondary_model = received_config.get("secondaryAsrModel")
            normalized_secondary_model = (
                str(raw_secondary_model).strip()
                if isinstance(raw_secondary_model, str) and raw_secondary_model.strip()
                else None
            )
            settings_manager.set_setting("secondaryAsrModel", normalized_secondary_model, save=False)
            log_text(
                "CONFIG",
                f"Secondary ASR model set to: {normalized_secondary_model if normalized_secondary_model else 'None'}",
            )
            worker = self._get_secondary_asr_worker()
            if worker is not None and normalized_secondary_model:
                model_to_warm = normalized_secondary_model

                def _warm_secondary_model():
                    try:
                        worker.warm_model(
                            model_to_warm,
                            timeout_seconds=getattr(self, "_secondary_worker_timeout_seconds", 240.0),
                        )
                        log_text(
                            "SECONDARY_ASR",
                            f"Secondary worker warm-up ready for model: {model_to_warm}",
                        )
                    except Exception as warm_error:
                        log_text(
                            "SECONDARY_ASR",
                            f"Secondary worker warm-up skipped: {warm_error}",
                        )

                threading.Thread(
                    target=_warm_secondary_model,
                    name="secondary-asr-warmup",
                    daemon=True,
                ).start()

        if "selectedMicrophoneId" in received_config:
            selected_mic = received_config.get("selectedMicrophoneId")
            normalized_mic = "default" if selected_mic in (None, "", "default") else str(selected_mic)
            settings_manager.set_setting("selectedMicrophoneId", normalized_mic, save=False)
            self.audio_handler.set_input_device_preference(normalized_mic)
            log_text("CONFIG", f"Selected microphone set to: {normalized_mic}")

        for shortcut_key, default_value in (
            ("transcribeShortcut", "Option+Space"),
            ("stopTranscribingShortcut", "Cmd+Shift+S"),
            ("retranscribeBackupShortcut", "Ctrl+Option+R"),
        ):
            if shortcut_key in received_config:
                settings_manager.set_setting(
                    shortcut_key,
                    str(received_config.get(shortcut_key) or default_value),
                    save=False,
                )

        self._apply_hotkey_settings_from_store(received_config)
        settings_manager.save_settings()
        self._handle_status_update("Configuration applied.", "grey")
        self._update_app_state()

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

    def _get_lifecycle(self) -> DictationLifecycleStateMachine:
        lifecycle = getattr(self, "_lifecycle", None)
        if lifecycle is None:
            lifecycle = DictationLifecycleStateMachine(initial_state="idle")
            self._lifecycle = lifecycle
        return lifecycle

    def _get_text_inserter(self) -> SafeTextInserter:
        inserter = getattr(self, "_text_inserter", None)
        if inserter is None:
            inserter = SafeTextInserter(
                paste_callback=send_text_to_citrix,
                status_callback=self._handle_status_update,
                log_callback=log_text,
            )
            self._text_inserter = inserter
        return inserter

    def _get_secondary_asr_worker(self) -> Optional[SecondaryAsrWorkerClient]:
        if not getattr(self, "_secondary_worker_enabled", False):
            return None

        worker = getattr(self, "_secondary_asr_worker", None)
        if worker is not None:
            return worker

        queue_limit_raw = os.getenv("CT_SECONDARY_ASR_QUEUE_LIMIT", "8").strip()
        try:
            queue_limit = max(1, int(queue_limit_raw))
        except ValueError:
            queue_limit = 8

        worker = SecondaryAsrWorkerClient(
            timeout_seconds=getattr(self, "_secondary_worker_timeout_seconds", 240.0),
            queue_size=queue_limit,
            log_callback=log_text,
        )
        self._secondary_asr_worker = worker
        return worker

    def _run_secondary_retranscribe(self, audio_path: str, model_id: str) -> str:
        worker = self._get_secondary_asr_worker()
        if worker is not None:
            response = worker.transcribe_audio_file(
                audio_path,
                model_id,
                timeout_seconds=getattr(self, "_secondary_worker_timeout_seconds", 240.0),
            )
            return str(response.get("transcript") or "")

        # Test/dev fallback path when __init__ has been bypassed.
        self.transcription_handler.ensure_model_assets(model_id)
        return self.transcription_handler.retranscribe_audio_file(audio_path, model_id)

    def _transition_lifecycle(
        self,
        next_state: str,
        reason: str,
        *,
        force: bool = False,
        publish: bool = False,
    ) -> None:
        lifecycle = self._get_lifecycle()
        changed = False
        try:
            changed = lifecycle.transition(next_state, reason=reason, force=force)
        except ValueError as error:
            log_text("LIFECYCLE", f"Invalid transition ignored: {error}")
        if publish and changed:
            self._publish_lifecycle_state()

    def _sync_lifecycle_from_state_payload(self, state_data: Dict[str, Any], *, reason: str) -> str:
        lifecycle = self._get_lifecycle()
        audio_state = state_data.get("audioState", "inactive")
        program_active = bool(state_data.get("programActive", False))
        wake_word_enabled = bool(state_data.get("wakeWordEnabled", True))
        microphone_error = state_data.get("microphoneError")
        return lifecycle.sync_from_audio_state(
            audio_state=audio_state,
            program_active=program_active,
            wake_word_enabled=wake_word_enabled,
            microphone_error=microphone_error if isinstance(microphone_error, str) else None,
            reason=reason,
        )

    def _compose_state_payload(self, state_data: Dict[str, Any], *, source: str) -> Dict[str, Any]:
        explicit_lifecycle = state_data.get("dictationLifecycle")
        if ipc_contract.validate_lifecycle_state(explicit_lifecycle):
            self._transition_lifecycle(
                explicit_lifecycle,
                f"{source}:explicit_lifecycle",
                force=True,
                publish=False,
            )
            lifecycle_state = explicit_lifecycle
        else:
            lifecycle_state = self._sync_lifecycle_from_state_payload(
                state_data, reason=f"{source}:{state_data.get('audioState', 'unknown')}"
            )
        lifecycle_snapshot = self._get_lifecycle().snapshot()
        merged = dict(state_data)
        merged["dictationLifecycle"] = lifecycle_state
        merged["dictationLifecycleReason"] = lifecycle_snapshot.reason
        normalized_payload = ipc_contract.normalize_state_payload(merged, defaults=merged)
        return normalized_payload or merged

    def _emit_state_update(self, state_data: Dict[str, Any], *, source: str) -> None:
        payload = self._compose_state_payload(state_data, source=source)
        print(ipc_contract.with_prefix("state", payload), flush=True)

    def _publish_lifecycle_state(self) -> None:
        audio_state = "inactive"
        audio_handler_active = False
        wake_word_enabled = True
        try:
            audio_state = self.audio_handler.get_listening_state()
            audio_handler_active = bool(self.audio_handler._program_active)
            wake_word_enabled = bool(self.audio_handler.is_wake_word_enabled())
        except Exception:
            pass

        state_data = {
            "programActive": audio_handler_active,
            "audioState": audio_state,
            "isDictating": audio_state == "dictation",
            "currentMode": getattr(self, "_current_processing_mode", None),
            "wakeWordEnabled": wake_word_enabled,
            "dictationLifecycle": self._get_lifecycle().state,
        }
        self._emit_state_update(state_data, source="lifecycle_publish")

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
        self._transition_lifecycle("idle", "startup_initial_state", force=True)
        self._emit_state_update(initial_state_data, source="startup")
        
        self.hotkey_manager.start()
        self.start_backend_audio()
        
        # Start Local API
        self.api_server = LocalAPIServer(self)
        self.api_server.start()

        secondary_model = settings_manager.get_setting("secondaryAsrModel")
        if secondary_model:
            worker = self._get_secondary_asr_worker()
            if worker is not None:
                model_to_warm = str(secondary_model)

                def _startup_warm_secondary():
                    try:
                        worker.warm_model(
                            model_to_warm,
                            timeout_seconds=getattr(self, "_secondary_worker_timeout_seconds", 240.0),
                        )
                        log_text(
                            "SECONDARY_ASR",
                            f"Secondary worker startup warm-up ready for model: {model_to_warm}",
                        )
                    except Exception as warm_error:
                        log_text(
                            "SECONDARY_ASR",
                            f"Secondary startup warm-up skipped: {warm_error}",
                        )

                threading.Thread(
                    target=_startup_warm_secondary,
                    name="secondary-asr-startup",
                    daemon=True,
                ).start()
        
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
            if self.medication_autolearn_service:
                self.medication_autolearn_service.shutdown()
                set_global_medication_autolearn_service(None)
            # Ensure PyAudio is terminated if AudioHandler didn't do it
            if hasattr(self.audio_handler, "_p") and self.audio_handler._p:
                self.audio_handler.terminate_pyaudio()
            self._bg_retranscribe_cancel.set()

            secondary_worker = getattr(self, "_secondary_asr_worker", None)
            if secondary_worker is not None:
                secondary_worker.shutdown()

            if hasattr(self, "transcription_handler") and self.transcription_handler:
                self.transcription_handler.shutdown()

        except Exception as e:
            log_text("SHUTDOWN_ERROR", f"Error during shutdown: {e}")
            print(f"ERROR: Error during shutdown: {e}", flush=True)
        finally:
            self._handle_status_update("Shutdown complete.", "grey")
            log_text("SHUTDOWN", "Backend shutdown complete.")

    # --- Callback Methods for Handlers ---

    def _is_dictation_or_processing_active(self) -> bool:
        try:
            audio_state = self.audio_handler.get_listening_state()
        except Exception:
            audio_state = ""
        if audio_state in {"dictation", "processing"}:
            return True
        return bool(getattr(self, "_current_processing_mode", None))

    def _handle_medication_autolearn_summary(self, summary: Dict[str, Any]) -> None:
        message = (
            "Medication auto-learn: "
            f"scanned {int(summary.get('scannedRecords', 0) or 0)}, "
            f"imported {int(summary.get('importedMappings', 0) or 0)}, "
            f"queued {int(summary.get('queuedReviews', 0) or 0)}, "
            f"pending {int(summary.get('pendingReviews', 0) or 0)}"
        )
        self._handle_status_update(message, "grey")
        if summary.get("error"):
            log_text("MEDICATION_AUTOLEARN_ERROR", str(summary.get("error")))

    def _handle_status_update(self, message: str, color: str):
        """Receives status updates from handlers and prints them for Electron."""
        if ipc_contract.is_prefixed_message(message, "audioMetrics"):
            payload_text = ipc_contract.strip_prefix(message, "audioMetrics")
            try:
                raw_payload = json.loads(payload_text or "{}")
            except json.JSONDecodeError:
                raw_payload = {}
            metrics_payload = ipc_contract.normalize_audio_metrics_payload(raw_payload)
            amp_value = metrics_payload.get("amplitude", 0) if metrics_payload else 0
            self._session_store.set_audio_amp(int(amp_value))
            if metrics_payload is not None:
                print(ipc_contract.with_prefix("audioMetrics", metrics_payload), flush=True)
            else:
                print(message, flush=True)
        # Legacy passthrough for older backend messages.
        elif ipc_contract.is_prefixed_message(message, "audioAmplitudeLegacy"):
            try:
                amp_value = int(message.split(":", 1)[1].strip())
            except (ValueError, IndexError):
                amp_value = 0
            self._session_store.set_audio_amp(amp_value)
            print(message, flush=True)
        elif ipc_contract.is_prefixed_message(message, "audioLevelsLegacy"):
            print(message, flush=True)
        elif color == "STATE_MSG":
            if ipc_contract.is_prefixed_message(message, "state"):
                try:
                    state_data = json.loads(ipc_contract.strip_prefix(message, "state") or "{}")
                    if isinstance(state_data, dict):
                        self._emit_state_update(state_data, source="audio_handler")
                        if state_data.get("microphoneError"):
                            log_text(
                                "MIC_ERROR_STATE",
                                f"Microphone error: {state_data['microphoneError']}",
                            )
                            error_msg = state_data["microphoneError"]
                            if len(error_msg) > 80:
                                error_msg = error_msg[:77] + "..."
                            print(
                                ipc_contract.with_prefix("status", f"orange:{error_msg}"),
                                flush=True,
                            )
                        return
                except (json.JSONDecodeError, KeyError, TypeError) as error:
                    log_text("STATE_PARSE_ERROR", f"Error parsing state message: {error}")
            print(message, flush=True)
        else:
            # Otherwise, print other status updates with the prefix
            print(ipc_contract.with_prefix("status", f"{color}:{message}"), flush=True)

    def handle_vocabulary_api_command_line(self, command_line: str) -> None:
        """Handle VOCABULARY_API command messages from Electron."""
        try:
            # Format: VOCABULARY_API:messageId:{"command": "...", "data": {...}}
            parts = command_line.split(":", 2)
            if len(parts) < 3:
                log_text("VOCAB_ERROR", f"Invalid vocabulary API command format: {command_line}")
                return

            message_id = parts[1]
            command_data = json.loads(parts[2])
            result = self.vocabulary_api.handle_command(
                command_data.get("command", ""),
                **command_data.get("data", {})
            )

            response_message = f"VOCAB_RESPONSE:{message_id}:{json.dumps(result)}"
            print(response_message, flush=True)
            sys.stdout.flush()

            log_text(
                "VOCAB_API",
                f"Handled vocabulary command: {command_data.get('command')} - Success: {result.get('success')}",
            )
        except json.JSONDecodeError as error:
            log_text("VOCAB_ERROR", f"JSON decode error in vocabulary API: {error}")
        except Exception as error:
            log_text("VOCAB_ERROR", f"Error handling vocabulary API: {error}")
            if 'message_id' in locals():
                error_response = f"VOCAB_RESPONSE:{message_id}:{json.dumps({'success': False, 'error': str(error)})}"
                print(error_response, flush=True)
                sys.stdout.flush()

    # Removed _process_status_queue method

    def _handle_wake_word(self, command: str):
        """Called by AudioHandler when a wake word is detected."""
        log_text("WAKE_WORD", f"Command received: {command}")

        if not self._program_active:
            self._handle_status_update("Program inactive, wake word ignored.", "orange")
            # Ensure audio handler goes back to activation state if it changed
            self.audio_handler.set_listening_state("activation")
            self._transition_lifecycle("idle", "wake_word_ignored_program_inactive", force=True)
            self._update_app_state()
            return

        if command == config.COMMAND_START_DICTATE:
            # Cancel any in-flight background retranscription
            self._bg_retranscribe_cancel.set()
            self._bg_retranscribe_result = None
            self.medication_autolearn_service.notify_activity()

            self._current_processing_mode = "dictate"
            self._handle_status_update("Dictation started.", "green")
            self._current_dictation_started_at = time.time()
            self._transition_lifecycle("recording", "wake_word_start_dictate", force=True)
        else:
            log_text("WAKE_WORD", f"Unknown command from wake word: {command}")
            self.audio_handler.set_listening_state(
                "activation"
            )  # Go back if command invalid
            self._transition_lifecycle("listening", "wake_word_unknown_command", force=True)
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
        self.medication_autolearn_service.notify_activity()
        self._handle_status_update("Speech ended. Transcribing...", "orange")
        self._transition_lifecycle("transcribing", "speech_end", publish=True)
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
        log_event(
            "TRANSCRIPTION_COMPLETE",
            "transcription_received",
            duration_seconds=round(duration, 2),
            raw_transcript=raw_text,
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
                    log_event(
                        "LLM_ENHANCE",
                        "enhancement_changed_transcript",
                        before_text=processed_text,
                        after_text=enhanced_text,
                    )
                    processed_text = enhanced_text
            
            processed_text = text_processor.clean_text(processed_text)
            
            # Log the processing if any changes were made
            if processed_text != raw_text.strip():
                log_event(
                    "TEXT_PROCESSED",
                    "post_processing_changed_text",
                    original_text=raw_text.strip(),
                    processed_text=processed_text,
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
            print(ipc_contract.with_prefix("finalTranscript", processed_text), flush=True)
            if session_outcome.get("suppressPaste"):
                log_text(
                    "TRANSCRIPTION_COMPLETE",
                    f"Session {session_outcome.get('sessionId')} suppressPaste enabled; skipped clipboard send.",
                )
            else:
                self._transition_lifecycle(
                    "inserting",
                    "transcription_ready_for_insert",
                    force=True,
                    publish=True,
                )
                self._handle_status_update("Sending to Citrix...", "blue")
                insert_result = self._get_text_inserter().transactional_insert(
                    primary_text=processed_text,
                    source="transcription",
                )
                if insert_result.success:
                    log_text("TRANSCRIPTION_COMPLETE", "Text sent to Citrix via clipboard.")
                else:
                    log_text(
                        "TRANSCRIPTION_COMPLETE",
                        "Insert skipped because no replacement text was available.",
                    )
            self._handle_status_update("Transcription complete.", "green")
        else:
            # Empty transcription - always finish
            self._get_text_inserter().transactional_insert(
                primary_text="",
                source="transcription",
                append_trailing_space=False,
                on_no_text_message="Transcription returned empty; existing text was left unchanged.",
            )

        # Send history entry AFTER transcript so setLastHistoryEntry() finds the
        # correct (just-finalized) entry when linking.
        print(ipc_contract.with_prefix("historyEntry", history_record), flush=True)
        try:
            self.medication_autolearn_service.notify_dictation_completed()
        except Exception as auto_learn_error:
            log_text("MEDICATION_AUTOLEARN_ERROR", f"Failed to schedule auto-learn: {auto_learn_error}")

        # Reset state and return to listening
        self._current_processing_mode = None
        self.hotkey_manager.set_dictating_state(False)
        self.audio_handler.set_listening_state("activation")
        self._transition_lifecycle("listening", "transcription_complete_reset", force=True)
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

    def _handle_start_dictate_hotkey(self, current_audio_state: str, trigger_command: str) -> bool:
        """Start dictation via hotkey when state allows it."""
        log_text("HOTKEY", f"Checking audio state for command: {trigger_command}")
        if current_audio_state == "dictation":
            self._handle_status_update(
                "Already dictating, ignoring start command.", "orange"
            )
            log_text("HOTKEY", "Already dictating, command ignored.")
            return False
        if current_audio_state == "processing":
            self._handle_status_update(
                "Currently processing, ignoring start command.", "orange"
            )
            log_text("HOTKEY", "Currently processing, command ignored.")
            return False

        log_text(
            "HOTKEY",
            f"Audio state is '{current_audio_state}', triggering action for command: {trigger_command}",
        )
        self._handle_wake_word(config.COMMAND_START_DICTATE)
        log_text("HOTKEY", f"Called _handle_wake_word with command: {trigger_command}")
        return True

    def _handle_toggle_dictate_hotkey(self, current_audio_state: str):
        """Toggle dictation start/stop from a single hotkey."""
        if current_audio_state == "dictation":
            self._trigger_stop_dictation()
            return
        if current_audio_state == "processing":
            self._handle_status_update(
                "Currently processing, toggle ignored.", "orange"
            )
            return
        self._handle_start_dictate_hotkey(current_audio_state, config.COMMAND_TOGGLE_DICTATE)

    def _handle_stop_dictate_hotkey(self, current_audio_state: str):
        """Stop dictation hotkey handler."""
        if current_audio_state == "dictation":
            self._trigger_stop_dictation()
        else:
            self._handle_status_update(
                "Not dictating, stop command ignored.", "orange"
            )

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
                print(
                    ipc_contract.with_prefix(
                        "retranscribeStart", f"error:Re-transcribe failed: {e}"
                    ),
                    flush=True,
                )
                print(ipc_contract.with_prefix("retranscribeEnd", "error"), flush=True)
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
            self._handle_start_dictate_hotkey(current_audio_state, command)

        elif command == config.COMMAND_TOGGLE_DICTATE:
            self._handle_toggle_dictate_hotkey(current_audio_state)

        elif command == config.COMMAND_STOP_DICTATE:
            self._handle_stop_dictate_hotkey(current_audio_state)

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
        fallback_text = (self._last_raw_transcription or "").strip()
        secondary_model = settings_manager.get_setting("secondaryAsrModel")
        if not secondary_model:
            print(
                ipc_contract.with_prefix(
                    "retranscribeStart",
                    "error:No secondary ASR model configured. Set one in Settings.",
                ),
                flush=True,
            )
            print(ipc_contract.with_prefix("retranscribeEnd", "error"), flush=True)
            if fallback_text:
                self._get_text_inserter().transactional_insert(
                    primary_text="",
                    fallback_text=fallback_text,
                    source="re-transcription",
                    on_no_text_message="No secondary ASR model configured and no fallback text was available.",
                )
            else:
                self._handle_status_update(
                    "No secondary ASR model configured. Set one in Settings.", "orange"
                )
            self._transition_lifecycle(
                "listening", "retranscribe_no_secondary_model", force=True, publish=True
            )
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
                print(
                    ipc_contract.with_prefix(
                        "retranscribeStart", cached.get("modelId", secondary_model)
                    ),
                    flush=True,
                )
                print(ipc_contract.with_prefix("retranscribeEnd", "success"), flush=True)
                # Re-emit as a manual result so frontend updates the linked transcript entry.
                manual_payload = dict(cached)
                manual_payload["autoTriggered"] = False
                print(
                    ipc_contract.with_prefix("retranscribeQuickResult", manual_payload),
                    flush=True,
                )
                self._transition_lifecycle(
                    "inserting", "cached_retranscribe_insert", force=True, publish=True
                )
                self._get_text_inserter().transactional_insert(
                    primary_text=result_text,
                    fallback_text=fallback_text or None,
                    source="re-transcription",
                )
                self._handle_status_update("Re-transcription complete (cached).", "green")
                self._transition_lifecycle(
                    "listening", "cached_retranscribe_complete", force=True, publish=True
                )
                self._bg_retranscribe_result = None
                return

        entry_id = self._last_history_entry_id
        if not entry_id:
            print(
                ipc_contract.with_prefix(
                    "retranscribeStart", "error:No recent dictation to re-transcribe."
                ),
                flush=True,
            )
            print(ipc_contract.with_prefix("retranscribeEnd", "error"), flush=True)
            if fallback_text:
                self._get_text_inserter().transactional_insert(
                    primary_text="",
                    fallback_text=fallback_text,
                    source="re-transcription",
                    on_no_text_message="No recent dictation was available and no fallback text existed.",
                )
            else:
                self._handle_status_update("No recent dictation to re-transcribe.", "orange")
            self._transition_lifecycle(
                "listening", "retranscribe_no_entry", force=True, publish=True
            )
            return

        audio_path = os.path.join("data", "history", "audio", f"{entry_id}.wav")
        if not os.path.exists(audio_path):
            print(
                ipc_contract.with_prefix(
                    "retranscribeStart",
                    "error:Audio file not found for last dictation.",
                ),
                flush=True,
            )
            print(ipc_contract.with_prefix("retranscribeEnd", "error"), flush=True)
            if fallback_text:
                self._get_text_inserter().transactional_insert(
                    primary_text="",
                    fallback_text=fallback_text,
                    source="re-transcription",
                    on_no_text_message="Audio for re-transcription is unavailable and no fallback text existed.",
                )
            else:
                self._handle_status_update("Audio file not found for last dictation.", "orange")
            self._transition_lifecycle(
                "listening", "retranscribe_audio_missing", force=True, publish=True
            )
            return

        print(
            ipc_contract.with_prefix(
                "retranscribeStart",
                f"{secondary_model} (preparing model assets if needed)",
            ),
            flush=True,
        )
        pending_message = (
            f"Preparing {secondary_model} for re-transcription (first run may take longer)..."
        )
        self._get_text_inserter().notify_pending(pending_message)
        self._transition_lifecycle(
            "transcribing", "retranscribe_requested", force=True, publish=True
        )

        def retranscribe_worker():
            try:
                self._handle_status_update(f"Re-transcribing with {secondary_model}...", "blue")
                self._transition_lifecycle(
                    "transcribing", "retranscribe_model_ready", force=True, publish=True
                )
                start_time = time.time()
                result_text = self._run_secondary_retranscribe(audio_path, secondary_model)

                if result_text:
                    use_llm = settings_manager.get_setting("useMedGemmaPostProcessing", False)
                    if use_llm and secondary_model == "google/medasr":
                        result_text = llm_postprocessor.enhance_medical_transcription(result_text)
                    result_text = text_processor.clean_text(result_text)

                duration = time.time() - start_time

                if result_text:
                    result_payload = {
                        "success": True,
                        "entryId": entry_id,
                        "modelId": secondary_model,
                        "transcript": result_text,
                        "duration": round(duration, 2),
                    }
                    print(ipc_contract.with_prefix("retranscribeEnd", "success"), flush=True)
                    print(
                        ipc_contract.with_prefix("retranscribeQuickResult", result_payload),
                        flush=True,
                    )
                    self._transition_lifecycle(
                        "inserting", "retranscribe_insert_ready", force=True, publish=True
                    )
                    insert_result = self._get_text_inserter().transactional_insert(
                        primary_text=result_text,
                        fallback_text=fallback_text or None,
                        source="re-transcription",
                    )
                    if insert_result.success:
                        self._handle_status_update("Re-transcription complete.", "green")
                    else:
                        self._handle_status_update(
                            "Re-transcription finished but no replacement text was available.",
                            "orange",
                        )
                    self._transition_lifecycle(
                        "listening", "retranscribe_complete", force=True, publish=True
                    )
                else:
                    error_payload = {
                        "success": False,
                        "entryId": entry_id,
                        "modelId": secondary_model,
                        "error": "Re-transcription returned empty text.",
                    }
                    print(ipc_contract.with_prefix("retranscribeEnd", "error"), flush=True)
                    print(
                        ipc_contract.with_prefix("retranscribeQuickResult", error_payload),
                        flush=True,
                    )
                    self._get_text_inserter().transactional_insert(
                        primary_text="",
                        fallback_text=fallback_text or None,
                        source="re-transcription",
                        on_no_text_message="Re-transcription returned empty; existing text was left unchanged.",
                    )
                    self._transition_lifecycle(
                        "listening", "retranscribe_empty", force=True, publish=True
                    )

            except Exception as e:
                log_text("RETRANSCRIBE_ERROR", f"Quick retranscribe failed: {e}")
                error_payload = {
                    "success": False,
                    "entryId": entry_id,
                    "modelId": secondary_model,
                    "error": str(e)
                }
                print(ipc_contract.with_prefix("retranscribeEnd", "error"), flush=True)
                print(
                    ipc_contract.with_prefix("retranscribeQuickResult", error_payload),
                    flush=True,
                )
                self._get_text_inserter().transactional_insert(
                    primary_text="",
                    fallback_text=fallback_text or None,
                    source="re-transcription",
                    on_no_text_message=f"Re-transcription failed: {e}. Existing text was left unchanged.",
                )
                self._transition_lifecycle(
                    "error", "retranscribe_exception", force=True, publish=True
                )

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
                result_text = self._run_secondary_retranscribe(audio_path, secondary_model)

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

                if result_text:
                    result_payload = {
                        "success": True,
                        "entryId": entry_id,
                        "modelId": secondary_model,
                        "transcript": result_text,
                        "duration": round(duration, 2),
                        "autoTriggered": True
                    }

                    # Cache the result so quick-retranscribe hotkey can use it immediately
                    self._bg_retranscribe_result = result_payload

                    print(
                        ipc_contract.with_prefix("retranscribeQuickResult", result_payload),
                        flush=True,
                    )
                    log_text("BG_RETRANSCRIBE", f"Background retranscribe complete in {duration:.2f}s")
                else:
                    error_payload = {
                        "success": False,
                        "entryId": entry_id,
                        "modelId": secondary_model,
                        "error": "Background re-transcription returned empty text.",
                        "autoTriggered": True,
                    }
                    print(
                        ipc_contract.with_prefix("retranscribeQuickResult", error_payload),
                        flush=True,
                    )
                    log_text("BG_RETRANSCRIBE", "Background retranscribe returned empty text")

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
                print(
                    ipc_contract.with_prefix("retranscribeQuickResult", error_payload),
                    flush=True,
                )

        thread = threading.Thread(target=bg_worker, daemon=True)
        self._bg_retranscribe_thread = thread
        thread.start()

    # --- Command Handling Methods (Triggered by stdin) ---

    def _initialize_stdin_dispatch(self) -> None:
        self._stdin_exact_handlers = {
            "STOP_DICTATION": self._handle_stop_dictation_command,
            "ABORT_DICTATION": self._handle_abort_dictation_command,
            "GET_HOTKEYS": self._handle_get_hotkeys_command,
            "TOGGLE_ACTIVE": self._handle_toggle_active_command,
            "RESTART_APP": self._handle_restart_command,
            "start_dictate": self._handle_start_dictate_command,
            "MODELS_REQUEST": self._handle_models_request_command,
            "SHUTDOWN": self._handle_shutdown_command,
        }
        self._stdin_prefix_handlers = (
            ("CONFIG:", self._handle_config_command),
            ("SET_APP_STATE:", self._handle_set_app_state_command),
            ("SET_HOTKEYS_SUSPENDED:", self._handle_set_hotkeys_suspended_command),
            ("VOCABULARY_API:", self._handle_vocabulary_api_command),
            ("ENSURE_MODEL:", self._handle_ensure_model_command),
            ("LIST_MICROPHONES:", self._handle_list_microphones_command),
            ("REPASTE:", self._handle_repaste_command),
            ("RETRANSCRIBE_AUDIO:", self._handle_retranscribe_audio_command),
        )

    def process_stdin_command(self, command_line: str) -> bool:
        """Dispatch a single stdin command. Returns False when shutdown is requested."""
        exact_handler = self._stdin_exact_handlers.get(command_line)
        if exact_handler is not None:
            return bool(exact_handler(command_line))

        for prefix, handler in self._stdin_prefix_handlers:
            if command_line.startswith(prefix):
                return bool(handler(command_line))

        log_text("COMMAND_UNKNOWN", f"Unknown command received: {command_line}")
        print(f"UNKNOWN_COMMAND:{command_line}", flush=True)
        sys.stdout.flush()
        return True

    def _handle_config_command(self, command_line: str) -> bool:
        log_text("STARTUP_TRACE", "Received CONFIG: command.")
        config_str = command_line[len("CONFIG:") :]
        try:
            received_config = json.loads(config_str)
            log_text("CONFIG", "Configuration received from Electron.")
            log_text("STARTUP_TRACE", f"Successfully parsed config JSON: {received_config}")
            self.apply_runtime_config(received_config)
        except json.JSONDecodeError as error:
            log_text("CONFIG_ERROR", f"JSON decode error on config: {error}")
            self._handle_status_update(f"Config JSON error: {error}", "red")
        return True

    def _handle_stop_dictation_command(self, _command_line: str) -> bool:
        self._trigger_stop_dictation()
        return True

    def _handle_abort_dictation_command(self, _command_line: str) -> bool:
        self._trigger_abort_dictation()
        return True

    def _handle_get_hotkeys_command(self, _command_line: str) -> bool:
        self._send_hotkeys_info()
        return True

    def _handle_toggle_active_command(self, _command_line: str) -> bool:
        self._toggle_program_active()
        return True

    def _handle_restart_command(self, _command_line: str) -> bool:
        self._trigger_restart()
        return True

    def _handle_set_app_state_command(self, command_line: str) -> bool:
        try:
            active_status = command_line[len("SET_APP_STATE:") :]
            active = active_status.lower() == "true"
            self.audio_handler.set_program_active(active)
            self._program_active = active
            log_text("COMMAND", f"Set program active state via command: {active}")
            self._update_app_state()
        except ValueError:
            log_text("COMMAND_ERROR", f"Invalid active state command format: {command_line}")
            self._handle_status_update("Invalid state command.", "red")
        return True

    def _handle_set_hotkeys_suspended_command(self, command_line: str) -> bool:
        try:
            suspended_status = command_line[len("SET_HOTKEYS_SUSPENDED:") :].strip().lower()
            suspended = suspended_status == "true"
            self.hotkey_manager.set_hotkeys_suspended(suspended)
            log_text("COMMAND", f"Hotkeys suspended: {suspended}")
        except Exception as hotkey_suspend_error:
            log_text(
                "COMMAND_ERROR",
                f"Failed to set hotkey suspension state: {hotkey_suspend_error}",
            )
        return True

    def _handle_vocabulary_api_command(self, command_line: str) -> bool:
        self.handle_vocabulary_api_command_line(command_line)
        return True

    def _handle_ensure_model_command(self, command_line: str) -> bool:
        parts = command_line.split(":", 2)
        if len(parts) < 3:
            log_text("COMMAND_ERROR", f"Invalid ENSURE_MODEL command: {command_line}")
            return True

        request_id = parts[1]
        repo_id = parts[2]
        if repo_id.lower().startswith("apple:"):
            helper_candidates = [
                os.path.abspath(config.resolve_resource_path("AppleSpeechHelper.app")),
                os.path.abspath(
                    os.path.join(
                        os.path.dirname(__file__),
                        "tools",
                        "apple_speech_helper",
                        "dist",
                        "AppleSpeechHelper.app",
                    )
                ),
            ]
            helper_path = next(
                (
                    candidate
                    for candidate in helper_candidates
                    if os.path.isdir(candidate) and candidate.lower().endswith(".app")
                ),
                None,
            )
            if not helper_path:
                error_payload = {
                    "success": False,
                    "modelId": repo_id,
                    "error": "AppleSpeechHelper.app not found. Build it with: bash tools/apple_speech_helper/build.sh",
                }
                print(f"MODEL_ERROR:{request_id}:{json.dumps(error_payload)}", flush=True)
                sys.stdout.flush()
                log_text("COMMAND_ERROR", f"Apple model selected but helper missing: {repo_id}")
                return True

            response = {
                "success": True,
                "modelId": repo_id,
                "localPath": helper_path,
                "message": "Apple Speech selected (helper found; no model download required).",
            }
            print(f"MODEL_READY:{request_id}:{json.dumps(response)}", flush=True)
            sys.stdout.flush()
            log_text("COMMAND", f"No-op ensure for Apple model: {repo_id}")
            return True

        try:
            local_path = self.transcription_handler.ensure_model_assets(repo_id)
            response = {
                "success": True,
                "modelId": repo_id,
                "localPath": local_path,
                "message": "Model assets ready.",
            }
            print(f"MODEL_READY:{request_id}:{json.dumps(response)}", flush=True)
            sys.stdout.flush()
            log_text("COMMAND", f"Model assets ensured for {repo_id}")
        except Exception as ensure_error:
            error_payload = {
                "success": False,
                "modelId": repo_id,
                "error": str(ensure_error),
            }
            print(f"MODEL_ERROR:{request_id}:{json.dumps(error_payload)}", flush=True)
            sys.stdout.flush()
            log_text("COMMAND_ERROR", f"Failed to ensure model {repo_id}: {ensure_error}")
        return True

    def _handle_list_microphones_command(self, command_line: str) -> bool:
        parts = command_line.split(":", 1)
        request_id = parts[1] if len(parts) > 1 else ""
        try:
            devices = self.audio_handler.list_input_devices()
            response = {"success": True, "devices": devices}
        except Exception as microphone_error:
            response = {"success": False, "error": str(microphone_error), "devices": []}

        print(
            f"MICROPHONES_LIST:{request_id}:{json.dumps(response, ensure_ascii=False)}",
            flush=True,
        )
        sys.stdout.flush()
        return True

    def _handle_repaste_command(self, command_line: str) -> bool:
        repaste_text = command_line[len("REPASTE:") :]
        if repaste_text:
            log_text("REPASTE", f"Re-pasting text: {repaste_text[:50]}...")
            self._get_text_inserter().transactional_insert(
                primary_text=repaste_text,
                source="repaste",
            )
        else:
            log_text("REPASTE", "Empty repaste text, ignoring.")
        return True

    def _handle_start_dictate_command(self, _command_line: str) -> bool:
        self._handle_hotkey(config.COMMAND_START_DICTATE)
        return True

    def _handle_models_request_command(self, _command_line: str) -> bool:
        models_payload = json.dumps(config.AVAILABLE_ASR_MODELS)
        print(f"MODELS_LIST:{models_payload}", flush=True)
        sys.stdout.flush()
        log_text("COMMAND", "Sent MODELS_LIST to Electron")
        return True

    def _handle_retranscribe_audio_command(self, command_line: str) -> bool:
        request_id = ""
        try:
            parts = command_line.split(":", 3)
            if len(parts) < 4:
                log_text("RETRANSCRIBE_ERROR", f"Invalid RETRANSCRIBE_AUDIO format: {command_line}")
                return True

            request_id = parts[1]
            entry_id = parts[2]
            model_id = parts[3]

            log_text("RETRANSCRIBE", f"Starting retranscription: entry={entry_id}, model={model_id}")

            audio_path = os.path.join("data", "history", "audio", f"{entry_id}.wav")
            if not os.path.exists(audio_path):
                error_payload = {
                    "success": False,
                    "error": f"Audio file not found: {audio_path}",
                }
                print(f"RETRANSCRIBE_RESULT:{request_id}:{json.dumps(error_payload)}", flush=True)
                sys.stdout.flush()
                return True

            start_time = time.time()
            result_text = self._run_secondary_retranscribe(audio_path, model_id)

            if result_text:
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
                "duration": round(duration, 2),
            }
            print(f"RETRANSCRIBE_RESULT:{request_id}:{json.dumps(response)}", flush=True)
            sys.stdout.flush()
            log_text("RETRANSCRIBE", f"Completed retranscription in {duration:.2f}s")
        except Exception as retranscribe_error:
            log_text("RETRANSCRIBE_ERROR", f"Retranscription failed: {retranscribe_error}")
            error_payload = {
                "success": False,
                "error": str(retranscribe_error),
            }
            if request_id:
                print(f"RETRANSCRIBE_RESULT:{request_id}:{json.dumps(error_payload)}", flush=True)
                sys.stdout.flush()
        return True

    def _handle_shutdown_command(self, _command_line: str) -> bool:
        log_text("COMMAND", "Shutdown command received from Electron.")
        return False

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
            self._transition_lifecycle(
                "stopping", "manual_stop_requested", force=True, publish=True
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
        self._transition_lifecycle("listening", "dictation_aborted", force=True)
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
        for combo, command in self.hotkey_manager.get_hotkey_combinations().items():
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

        print(ipc_contract.with_prefix("hotkeys", hotkey_data), flush=True)

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
            self._transition_lifecycle("idle", "program_deactivated", force=True)
        else:
            self._transition_lifecycle("listening", "program_activated", force=True)
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
        self._emit_state_update(state_data, source="application")

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

        # Main loop to read commands from stdin
        for line in sys.stdin:
            command_line = line.strip()
            log_text("STDIN", f"Received command: {command_line}")
            should_continue = app.process_stdin_command(command_line)
            if not should_continue:
                break

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
