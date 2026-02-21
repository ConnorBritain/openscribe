import pyaudio
import os
import sys

# Make pynput imports conditional for CI compatibility
try:
    from pynput.keyboard import Key, KeyCode  # Import necessary keys
    PYNPUT_AVAILABLE = True
except ImportError:
    # pynput not available (CI environment)
    PYNPUT_AVAILABLE = False
    try:
        from . import config as _cfg  # circular-safe in runtime; only for attribute access
        if not getattr(_cfg, "MINIMAL_TERMINAL_OUTPUT", False):
            print("[WARN] pynput not available in config.py - using mock classes")
    except Exception:
        print("[WARN] pynput not available in config.py - using mock classes")
    # Create minimal mock classes for configuration
    class MockKey:
        cmd = "cmd"
        shift = "shift"
        alt = "alt"
        ctrl = "ctrl"
    
    class MockKeyCode:
        @staticmethod
        def from_char(char):
            class CharKey:
                def __init__(self, char):
                    self.char = char
                def __hash__(self):
                    return hash(self.char)
                def __eq__(self, other):
                    return hasattr(other, 'char') and self.char == other.char
            return CharKey(char)
    
    Key = MockKey()
    KeyCode = MockKeyCode()

# --- Path Resolution ---
def get_bundle_resource_path():
    """
    Get the path to the app bundle's Resources directory.
    Returns None if not running as a bundled app.
    """
    if getattr(sys, 'frozen', False):
        # Running as bundled executable
        # sys.executable points to the bundled executable
        # Navigate up to Resources directory
        executable_path = sys.executable
        # From: .../CitrixTranscriberBackend.app/Contents/MacOS/citrix-transcriber-backend
        # To: .../Resources/
        macos_dir = os.path.dirname(executable_path)
        backend_contents_dir = os.path.dirname(macos_dir)
        backend_app_dir = os.path.dirname(backend_contents_dir)
        resources_dir = os.path.dirname(backend_app_dir)
        return resources_dir
    return None

def resolve_resource_path(relative_path):
    """
    Resolve a resource path, handling both development and bundled modes.
    """
    bundle_resources = get_bundle_resource_path()
    if bundle_resources:
        # Running as bundled app - use absolute path from Resources
        return os.path.join(bundle_resources, relative_path)
    else:
        # Running in development - use relative path
        return relative_path

# --- Audio Parameters ---
SAMPLE_RATE = 16000
FRAME_DURATION_MS = 30
FRAME_SIZE = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)
AUDIO_FORMAT = pyaudio.paInt16
CHANNELS = 1
VAD_AGGRESSIVENESS = 1  # 0 (least aggressive) to 3 (most aggressive) - Reduced to fix silence detection
SILENCE_THRESHOLD_SECONDS = 1.5  # How long silence triggers processing
RING_BUFFER_DURATION_MS = 600  # How much audio to keep before trigger

# --- Paths ---
VOSK_MODEL_PATH = resolve_resource_path("vosk")
LOG_FILE = resolve_resource_path("transcript_log.txt")
TEMP_AUDIO_FOLDER = resolve_resource_path("temp_audio")
CHIME_SOUND_FILE = resolve_resource_path("chime.wav")  # Currently unused, but kept for potential future use

# Centralized models root so all components agree where models live on disk
MODELS_ROOT = resolve_resource_path("models")

# --- Model Configurations ---
AVAILABLE_ASR_MODELS = {
    # Curated stable set only
    "Parakeet-TDT-0.6B-v2": "mlx-community/parakeet-tdt-0.6b-v2",
    "Parakeet-TDT-0.6B-v3": "mlx-community/parakeet-tdt-0.6b-v3",
    "Whisper (large-v3-turbo)": "mlx-community/whisper-large-v3-turbo",
    "Voxtral Mini 3B (bf16)": "mlx-community/Voxtral-Mini-3B-2507-bf16",
    "MedASR (Medical)": "google/medasr",
    "Apple Speech (on-device, macOS)": "apple:speech:ondevice",
}
DEFAULT_ASR_MODEL = "mlx-community/whisper-large-v3-turbo"

# --- Prompts ---
DEFAULT_WHISPER_PROMPT = (
    "You are transcribing a professional encounter for documentation. "
    "Ensure the transcription is accurate, concise, and formatted appropriately. "
    "Use appropriate terminology when needed."
)

# --- MLX Whisper Decoding ---
# Override MLX Whisper transcribe settings to reduce trailing hallucinations.
# Values map directly to mlx_whisper.transcribe kwargs.
MLX_WHISPER_TRANSCRIBE_OPTIONS = {
    "temperature": 0.0,
    "condition_on_previous_text": False,
}
# Additional decode options for mlx_whisper.DecodingOptions (optional).
MLX_WHISPER_DECODE_OPTIONS = {}

# --- Hotkeys ---
# Define commands associated with hotkeys
COMMAND_TOGGLE_ACTIVE = "toggle_active"
COMMAND_START_DICTATE = "start_dictate"
COMMAND_STOP_DICTATE = "stop_dictate"  # Added for explicit stop hotkey
COMMAND_ABORT_DICTATE = "abort_dictate"  # Added for abort/cancel hotkey
COMMAND_RESTART = "restart"
COMMAND_SHOW_HOTKEYS = "show_hotkeys"
COMMAND_TOGGLE_MINI_MODE = "toggle_mini_mode"  # Added for mini mode toggle
COMMAND_RETRANSCRIBE_SECONDARY = "retranscribe_secondary"

# --- Wake Words ---
# Define words for different activation commands
# Structure: { category: [list_of_words] }
# Categories should match keys in command_map in audio_handler.py
WAKE_WORDS = {
    "dictate": ["note", "dictation", "dictate"],
}

# Define key combinations (using pynput format)
# Use Key.cmd for Command, Key.alt for Option, Key.ctrl for Control, Key.shift for Shift
# Example: {Key.cmd, Key.shift, 'a'}
HOTKEY_COMBINATIONS = {
    frozenset({Key.cmd, Key.shift, KeyCode.from_char("a")}): COMMAND_TOGGLE_ACTIVE,
    frozenset({Key.cmd, Key.shift, KeyCode.from_char("d")}): COMMAND_START_DICTATE,
    frozenset({Key.cmd, Key.shift, KeyCode.from_char("s")}): COMMAND_STOP_DICTATE,
    frozenset({Key.cmd, Key.shift, KeyCode.from_char("r")}): COMMAND_RESTART,
    frozenset({Key.cmd, Key.shift, KeyCode.from_char("h")}): COMMAND_SHOW_HOTKEYS,
    frozenset({Key.cmd, Key.shift, KeyCode.from_char("m")}): COMMAND_TOGGLE_MINI_MODE,
    frozenset({Key.cmd, Key.shift, KeyCode.from_char("x")}): COMMAND_RETRANSCRIBE_SECONDARY,
}

# --- GUI ---
APP_TITLE = "Professional Dictation Transcriber"
DEFAULT_THEME = "arc"  # Example theme, requires ttkthemes

# --- Other ---
TOKENIZERS_PARALLELISM = "false"  # Environment variable setting
LOG_TEXT_DETAIL_LEVEL = 1  # 0 = basic, 1 = detailed, etc. (currently informational)
SEND_TO_CITRIX_ENABLED = True  # Set to False to only copy to clipboard without pasting
LOCAL_API_PORT = 5050  # Port for the local background API server

# When copying to clipboard for legacy apps, replace non-breaking hyphens, fancy quotes,
# and other unicode punctuation with ASCII-safe equivalents.
SANITIZE_CLIPBOARD_FOR_LEGACY = True

# --- Terminal Output Controls ---
# Enable to drastically reduce stdout noise while keeping full file logs via utils.log_text
MINIMAL_TERMINAL_OUTPUT = True
# Labels that are still allowed to be printed by utils.log_text when MINIMAL_TERMINAL_OUTPUT is True
TERMINAL_LOG_WHITELIST = {
    "STARTUP",
    "INIT",
    "INIT_ERROR",
    "ERROR",
    "CRITICAL_ERROR",
    "SHUTDOWN",
    "LLM_ERROR",
    "CONFIG_ERROR",
    "PIPE_ERROR",
    "STATE_CHANGE",
}

# --- Environment overrides ---
# CT_VERBOSE=1 disables minimal terminal mode
_ct_verbose = os.getenv("CT_VERBOSE")
if _ct_verbose is not None:
    try:
        MINIMAL_TERMINAL_OUTPUT = not (_ct_verbose.strip() in ["1", "true", "True", "yes", "on"])
    except Exception:
        pass

# CT_LOG_WHITELIST="A,B,C" adds labels to terminal whitelist
_ct_log_whitelist = os.getenv("CT_LOG_WHITELIST")
if _ct_log_whitelist:
    try:
        for lbl in [s.strip() for s in _ct_log_whitelist.split(",") if s.strip()]:
            TERMINAL_LOG_WHITELIST.add(lbl)
    except Exception:
        pass
