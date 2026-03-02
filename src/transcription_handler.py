# Make imports conditional for CI compatibility
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    # Keep warning in stdout only if minimal mode is disabled
    try:
        from src.config import config as _cfg
        if not getattr(_cfg, "MINIMAL_TERMINAL_OUTPUT", False):
            print("[WARN] numpy not available in transcription_handler.py - using mock")
    except Exception:
        print("[WARN] numpy not available in transcription_handler.py - using mock")
    # Create minimal mock numpy for CI
    class MockArray:
        def __init__(self, data):
            self.data = data
            self.size = len(data) if hasattr(data, '__len__') else 0
        
        def tobytes(self):
            return b"mock_audio_data"
        
        def astype(self, dtype):
            return self
    
    class MockNumpy:
        @staticmethod
        def frombuffer(data, dtype=None):
            return MockArray([])
        
        @staticmethod
        def array(data):
            return MockArray(data)
        
        int16 = "int16"
        ndarray = MockArray  # Add ndarray as a type alias for type annotations
    
    np = MockNumpy()

import time
import os
import wave
import shutil
import queue

try:
    import mlx_whisper
    MLX_WHISPER_AVAILABLE = True
except ImportError:
    MLX_WHISPER_AVAILABLE = False
    try:
        from src.config import config as _cfg
        if not getattr(_cfg, "MINIMAL_TERMINAL_OUTPUT", False):
            print("[WARN] mlx_whisper not available - Whisper transcription will be mocked")
    except Exception:
        print("[WARN] mlx_whisper not available - Whisper transcription will be mocked")

try:
    import parakeet_mlx
    PARAKEET_MLX_AVAILABLE = True
except ImportError:
    PARAKEET_MLX_AVAILABLE = False
    try:
        from src.config import config as _cfg
        if not getattr(_cfg, "MINIMAL_TERMINAL_OUTPUT", False):
            print("[WARN] parakeet_mlx not available - Parakeet transcription will be mocked")
    except Exception:
        print("[WARN] parakeet_mlx not available - Parakeet transcription will be mocked")

try:
    from mlx_audio.stt import generate as mlx_audio_generate
    MLX_AUDIO_AVAILABLE = True
except ImportError:
    MLX_AUDIO_AVAILABLE = False
    try:
        from src.config import config as _cfg
        if not getattr(_cfg, "MINIMAL_TERMINAL_OUTPUT", False):
            print("[WARN] mlx-audio not available - Voxtral transcription will be mocked")
    except Exception:
        print("[WARN] mlx-audio not available - Voxtral transcription will be mocked")

# Create mock transcription functions if neither library is available
if not MLX_WHISPER_AVAILABLE and not PARAKEET_MLX_AVAILABLE:
    print("[WARN] No ASR libraries available - all transcription will be mocked")
    class MockMLXWhisper:
        @staticmethod
        def transcribe(audio_path, path_or_hf_repo, language=None, temperature=None, **kwargs):
            return {
                "text": f"[MOCK TRANSCRIPTION] Audio from {audio_path}",
                "language": "en",
                "segments": []
            }
    
    mlx_whisper = MockMLXWhisper()
    
    class MockParakeetMLX:
        @staticmethod
        def transcribe_from_file(audio_path, model_id, **kwargs):
            return f"[MOCK PARAKEET TRANSCRIPTION] Audio from {audio_path}"
    
    parakeet_mlx = MockParakeetMLX()

import threading

# Optional Transformers fallback for non-MLX Whisper repos
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    torch = None  # type: ignore

try:
    from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline as hf_pipeline
    from transformers import AutoModelForCTC
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False
    AutoModelForSpeechSeq2Seq = None  # type: ignore
    AutoProcessor = None  # type: ignore
    AutoModelForCTC = None  # type: ignore
    hf_pipeline = None  # type: ignore

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False
    try:
        from src.config import config as _cfg
        if not getattr(_cfg, "MINIMAL_TERMINAL_OUTPUT", False):
            print("[WARN] pyaudio not available in transcription_handler.py - using mock")
    except Exception:
        print("[WARN] pyaudio not available in transcription_handler.py - using mock")
    # Create mock pyaudio
    class MockPyAudio:
        paInt16 = "paInt16"
        
        @staticmethod
        def get_sample_size(format):
            return 2  # Default to 16-bit
    
    pyaudio = MockPyAudio()

import json
import platform
import subprocess
import tempfile
from pathlib import Path

try:
    from huggingface_hub import snapshot_download
    from huggingface_hub.utils import LocalEntryNotFoundError
    HUGGINGFACE_HUB_AVAILABLE = True
except ImportError:
    HUGGINGFACE_HUB_AVAILABLE = False
    try:
        from src.config import config as _cfg
        if not getattr(_cfg, "MINIMAL_TERMINAL_OUTPUT", False):
            print("[WARN] huggingface_hub not available - using mock download")
    except Exception:
        print("[WARN] huggingface_hub not available - using mock download")
    def snapshot_download(repo_id, local_dir=None, **kwargs):
        # Create a mock local directory structure
        mock_dir = local_dir or f"./mock_models/{repo_id.replace('/', '_')}"
        os.makedirs(mock_dir, exist_ok=True)
        
        # Create a mock config.json
        config_path = os.path.join(mock_dir, "config.json")
        if not os.path.exists(config_path):
            with open(config_path, "w") as f:
                json.dump({"sample_rate": 16000, "mock": True}, f)
        
        return mock_dir
    class LocalEntryNotFoundError(Exception):
        pass

# Import configuration constants
from src.config import config
from src.asr_runtime_manager import AsrRuntimeManager
from src.utils.utils import log_event, log_text  # Assuming a utils.py for logging
from src.vocabulary.vocabulary_manager import get_vocabulary_manager


class TranscriptionHandler:
    """Handles the transcription of audio data using multiple ASR libraries."""

    def __init__(
        self,
        on_transcription_complete_callback=None,
        on_status_update_callback=None,
        selected_asr_model=None,
    ):
        """
        Initializes the TranscriptionHandler.

        Args:
            on_transcription_complete_callback: Function to call when transcription finishes.
                                                Receives the transcribed text (str) and transcription time (float).
            on_status_update_callback: Function to call to update the application status display.
                                       Receives status text (str) and color (str).
            selected_asr_model: The Hugging Face ID of the ASR model to use (optional).
                               If not provided, will use saved settings or default.
        """
        self.on_transcription_complete = on_transcription_complete_callback
        self.on_status_update = on_status_update_callback
        self._temp_folder = config.TEMP_AUDIO_FOLDER
        self._sample_rate = config.SAMPLE_RATE
        self.local_model_path_prepared = None
        self.parakeet_model = None
        self.voxtral_model = None
        self._parakeet_loaded_model_id = None
        self._medasr_pipeline = None

        # Runtime model caches keep hot models in memory across dictation/retranscribe paths.
        # This avoids repeated cold loads when users switch between a small set of models.
        cache_limit_raw = os.getenv("CT_ASR_RUNTIME_CACHE_LIMIT", "2").strip()
        try:
            self._runtime_cache_limit = max(1, int(cache_limit_raw))
        except ValueError:
            self._runtime_cache_limit = 2
        self._runtime_manager = AsrRuntimeManager(
            cache_limit=self._runtime_cache_limit,
            log_status=self._log_status,
        )

        # Keep primary transcription work in a bounded queue served by one long-lived worker
        # instead of spawning an unbounded thread per request.
        queue_size_raw = os.getenv("CT_PRIMARY_ASR_QUEUE_LIMIT", "2").strip()
        try:
            self._transcription_queue_size = max(1, int(queue_size_raw))
        except ValueError:
            self._transcription_queue_size = 2
        self._transcription_queue = queue.Queue(maxsize=self._transcription_queue_size)
        self._transcription_worker_stop = threading.Event()
        self._transcription_worker = threading.Thread(
            target=self._transcription_worker_loop,
            daemon=True,
            name="primary-asr-worker",
        )
        self._transcription_worker.start()

        # Use provided model, or saved settings, or config default (in that order)
        if selected_asr_model:
            self.selected_asr_model = selected_asr_model
        else:
            # Try to get from saved settings, fall back to config default
            try:
                from settings_manager import settings_manager
                self.selected_asr_model = settings_manager.get_setting("selectedAsrModel", config.DEFAULT_ASR_MODEL)
            except ImportError:
                # In case settings_manager is not available (testing, etc.)
                self.selected_asr_model = config.DEFAULT_ASR_MODEL

        # Ensure selected_asr_model is valid string; fallback to default
        if not self.selected_asr_model:
            self.selected_asr_model = config.DEFAULT_ASR_MODEL
        # Determine the model type and library to use
        self.model_type = self._detect_model_type(self.selected_asr_model)
        self._log_status(f"Detected model type: {self.model_type} for {self.selected_asr_model}", "grey")
        # Decide whisper backend explicitly: MLX vs Transformers
        self._whisper_backend = None
        if self.model_type == "whisper":
            self._whisper_backend = self._detect_whisper_backend(self.selected_asr_model)
            self._log_status(f"Selected whisper backend: {self._whisper_backend}", "grey")
        if self.model_type == "apple":
            self._log_status("Apple Speech selected (on-device, macOS). No model assets will be loaded.", "grey")
        if self.model_type == "voxtral" and not MLX_AUDIO_AVAILABLE:
            self._log_status(
                "Voxtral model selected but mlx-audio is not installed. Install mlx-audio to enable Voxtral transcription.",
                "red",
            )

        # Light mode to avoid heavy model loads (set CT_LIGHT_MODE=1 to enable)
        self._light_mode = os.getenv("CT_LIGHT_MODE", "0") == "1"
        if self._light_mode:
            self._log_status("CT_LIGHT_MODE enabled - skipping heavy ASR model loads", "orange")
            self.parakeet_model = None
            self.local_model_path_prepared = "./mock_model_path"
 
        # Prefer bundled/local copies of models to avoid network calls when firewalled
        if self.model_type != "apple" and (
            not getattr(self, "local_model_path_prepared", None)
            or self.local_model_path_prepared == "./mock_model_path"
        ):
            bundled_path = self._get_local_model_dir(self.selected_asr_model)
            if bundled_path:
                self.local_model_path_prepared = bundled_path
                self._log_status(
                    f"Using bundled ASR model from: {bundled_path}", "grey"
                )
                self._ensure_hf_offline_env()
            elif not self._light_mode and (MLX_WHISPER_AVAILABLE or PARAKEET_MLX_AVAILABLE or MLX_AUDIO_AVAILABLE):
                try:
                    ensured_path = self.ensure_model_assets(self.selected_asr_model)
                    if ensured_path:
                        self.local_model_path_prepared = ensured_path
                        self._log_status(
                            f"Model assets prepared at: {ensured_path}", "grey"
                        )
                except Exception as prep_err:
                    self._log_status(
                        f"Unable to prepare model assets for {self.selected_asr_model}: {prep_err}",
                        "red",
                    )

        # Load Parakeet model if needed (skip in light mode)
        if not self._light_mode and self.model_type != "apple":
            if self.model_type == "parakeet" and PARAKEET_MLX_AVAILABLE:
                try:
                    load_target = self.local_model_path_prepared or self.selected_asr_model
                    try:
                        self.parakeet_model = self._get_or_load_parakeet_model(load_target)
                    except Exception:
                        if load_target != self.selected_asr_model:
                            self._log_status(
                                "Direct path load failed, retrying with repository id…",
                                "orange",
                            )
                            self.parakeet_model = self._get_or_load_parakeet_model(self.selected_asr_model)
                        else:
                            raise
                except Exception as e:
                    self._log_status(f"Failed to load Parakeet model: {e}", "red")
                    raise RuntimeError(f"Failed to load Parakeet model: {e}") from e
            else:
                self.parakeet_model = None

        # Check if we're in a CI environment (missing key dependencies)
        if not MLX_WHISPER_AVAILABLE and not PARAKEET_MLX_AVAILABLE and not MLX_AUDIO_AVAILABLE and not TRANSFORMERS_AVAILABLE and not TORCH_AVAILABLE:
            self._log_status("Transcription handler initialized in CI mode - dependencies mocked", "orange")
            self.local_model_path_prepared = "./mock_model_path"
            return

        # Ensure temp audio folder exists
        if not os.path.exists(self._temp_folder):
            try:
                os.makedirs(self._temp_folder)
                self._log_status(
                    f"Created temporary audio folder: {self._temp_folder}", "green"
                )
            except OSError as e:
                self._log_status(
                    f"Error creating temp audio folder {self._temp_folder}: {e}", "red"
                )
                # Decide if this is fatal or if we can proceed without saving temp files
                raise RuntimeError(f"Failed to create temp audio folder: {e}") from e

        # For Whisper models using MLX backend, let mlx_whisper handle downloads from repo id
        if self.model_type == "whisper" and self._whisper_backend == "mlx" and not self._light_mode:
            if not getattr(self, "local_model_path_prepared", None) or self.local_model_path_prepared == "./mock_model_path":
                self.local_model_path_prepared = self.selected_asr_model  # fall back to repo id
            target_display = (
                self.local_model_path_prepared
                if self.local_model_path_prepared != self.selected_asr_model
                else f"repo:{self.selected_asr_model}"
            )
            self._log_status(
                f"Preparing Whisper backend with: {target_display}",
                "grey",
            )
        elif not self._light_mode and self.model_type == "parakeet":
            # For Parakeet models, prefer prepared local path if available
            self.local_model_path_prepared = self.local_model_path_prepared or self.selected_asr_model
            self._log_status(f"Parakeet model will use: {self.local_model_path_prepared}", "grey")

    def update_selected_asr_model(self, new_model_id: str):
        """Update ASR model at runtime and prepare required resources."""
        if not new_model_id or new_model_id == self.selected_asr_model:
            # No change
            return
        self._log_status(f"Updating ASR model to: {new_model_id}", "orange")
        self.selected_asr_model = new_model_id
        # Recompute model type
        self.model_type = self._detect_model_type(self.selected_asr_model)
        self._log_status(f"Detected model type: {self.model_type} for {self.selected_asr_model}", "grey")
        
        # Reset active pointers (runtime caches are preserved to keep hot models loaded).
        self.parakeet_model = None
        self.voxtral_model = None
        self._parakeet_loaded_model_id = None
        self.local_model_path_prepared = None

        if self.model_type == "voxtral" and not MLX_AUDIO_AVAILABLE:
            self._log_status(
                "Voxtral model selected but mlx-audio is not installed. Install mlx-audio to enable Voxtral transcription.",
                "red",
            )

        if self.model_type == "apple":
            # Nothing to load; helper handles recognition and permissions.
            return
        
        # Respect light mode - avoid heavy loads and downloads
        if getattr(self, "_light_mode", False):
            self._log_status("CT_LIGHT_MODE enabled - deferring heavy ASR model setup", "orange")
            self.local_model_path_prepared = "./mock_model_path"
            return

        # Handle CI/mock mode quickly
        if not MLX_WHISPER_AVAILABLE and not PARAKEET_MLX_AVAILABLE:
            self._log_status("ASR update in CI mode - dependencies mocked", "orange")
            self.local_model_path_prepared = "./mock_model_path"
            return

        # Prefer bundled assets if available when switching models
        bundled_path = self._get_local_model_dir(self.selected_asr_model)
        if bundled_path:
            self.local_model_path_prepared = bundled_path
            self._log_status(
                f"Using bundled ASR model from: {bundled_path}", "grey"
            )
            self._ensure_hf_offline_env()
            if self.model_type != "parakeet":
                return

        try:
            ensured_path = None
            if not getattr(self, "_light_mode", False):
                ensured_path = self.ensure_model_assets(self.selected_asr_model)

            if self.model_type == "parakeet":
                if PARAKEET_MLX_AVAILABLE:
                    load_target = ensured_path or self.local_model_path_prepared or self.selected_asr_model
                    try:
                        self.parakeet_model = self._get_or_load_parakeet_model(load_target)
                    except Exception:
                        if load_target != self.selected_asr_model:
                            self._log_status(
                                "Direct path load failed, retrying with repository id…",
                                "orange",
                            )
                            self.parakeet_model = self._get_or_load_parakeet_model(self.selected_asr_model)
                        else:
                            raise
                    # Track the prepared path (repo id if direct)
                    self.local_model_path_prepared = load_target
                else:
                    self._log_status("Parakeet library not available; cannot load model.", "red")
                    raise RuntimeError("Parakeet library not available")
            else:
                label = "Whisper" if self.model_type == "whisper" else "Voxtral"
                self._log_status(
                    f"Preparing local copy of {label} model: {self.selected_asr_model}",
                    "grey",
                )
                self.local_model_path_prepared = ensured_path or self._prepare_local_model_copy(
                    self.selected_asr_model
                )
                self._log_status(
                    f"Local {label} model prepared at: {self.local_model_path_prepared}",
                    "grey",
                )
        except Exception as e:
            self._log_status(f"Failed to update ASR model '{self.selected_asr_model}': {e}", "red")
            raise

    def _detect_model_type(self, model_id: str) -> str:
        """
        Detect whether the model is a Whisper or Parakeet model.
        
        Args:
            model_id: The Hugging Face model ID
            
        Returns:
            "whisper", "parakeet", or "voxtral"
        """
        model_id_lower = model_id.lower()
        if model_id_lower.startswith("apple:"):
            return "apple"
        if "voxtral" in model_id_lower:
            return "voxtral"
        if "medasr" in model_id_lower or model_id_lower == "google/medasr":
            return "medasr"
        if "parakeet" in model_id_lower:
            # Check if parakeet_mlx is available, if not, fall back to whisper
            if not PARAKEET_MLX_AVAILABLE:
                self._log_status(f"Parakeet model {model_id} selected but parakeet_mlx not available. Falling back to Whisper.", "orange")
                return "whisper"
            return "parakeet"
        elif "whisper" in model_id_lower:
            return "whisper"
        else:
            # Default to whisper for unknown models
            self._log_status(f"Unknown model type for {model_id}, defaulting to whisper", "orange")
            return "whisper"

    def _get_local_model_dir(self, model_id: str):
        """Return bundled model path if it exists and appears complete."""
        if not model_id:
            return None
        normalized_path = os.path.join(
            config.MODELS_ROOT,
            model_id.replace("/", os.sep),
        )
        config_file = os.path.join(normalized_path, "config.json")
        if not (os.path.isdir(normalized_path) and os.path.exists(config_file)):
            return None

        try:
            with open(config_file, "r", encoding="utf-8") as cfg_fh:
                cfg_data = json.load(cfg_fh) if config_file else {}
        except Exception:
            cfg_data = {}

        # MedASR models have model_type in config instead of dims
        is_medasr = "medasr" in model_id.lower()
        if is_medasr:
            # MedASR models have model_type and architectures in config.json
            if not isinstance(cfg_data, dict) or "model_type" not in cfg_data:
                return None
            # Check for model.safetensors instead of tokenizer.json as the main artifact
            model_file = os.path.join(normalized_path, "model.safetensors")
            if not os.path.exists(model_file):
                return None
            return normalized_path

        # Whisper/Parakeet/Voxtral models: check for valid config structure
        # MLX Whisper configs use flat keys (n_mels, n_audio_ctx, etc.) OR nested "dims"
        if not isinstance(cfg_data, dict):
            return None

        # Check for MLX Whisper flat config format (n_mels at top level)
        is_mlx_whisper_flat = "n_mels" in cfg_data and "n_audio_ctx" in cfg_data
        # Check for legacy dims-based config
        has_dims = "dims" in cfg_data
        # Check for Parakeet config (has vocab_size typically)
        is_parakeet = "parakeet" in model_id.lower()

        if not (is_mlx_whisper_flat or has_dims or is_parakeet):
            return None

        tokenizer_file = os.path.join(normalized_path, "tokenizer.json")
        if not os.path.exists(tokenizer_file):
            # MLX models may use various weight file formats
            weight_files = [
                os.path.join(normalized_path, "weights.npz"),
                os.path.join(normalized_path, "weights.safetensors"),
                os.path.join(normalized_path, "model.safetensors"),
            ]
            if not any(os.path.exists(wf) for wf in weight_files):
                return None

        return normalized_path

    @staticmethod
    def _ensure_hf_offline_env():
        """Prevent huggingface_hub from making network calls once models are local."""
        current = os.getenv("HF_HUB_OFFLINE", "").lower()
        if current not in {"1", "true", "yes"}:
            os.environ["HF_HUB_OFFLINE"] = "1"

    def _detect_whisper_backend(self, model_id: str) -> str:
        """Return 'mlx' for MLX-native repos, otherwise 'transformers'."""
        # Fallback to transformers if MLX is not available but Transformers is
        if not MLX_WHISPER_AVAILABLE and TRANSFORMERS_AVAILABLE:
            return "transformers"

        if not model_id:
            return "mlx"
        mid = model_id.lower()
        if mid.startswith("mlx-community/"):
            return "mlx"
        # Known non-MLX repos commonly using HF Transformers
        if any(mid.startswith(p) for p in [
            "openai/", "na0s/", "crystalcareai/", "distil-whisper/"
        ]):
            return "transformers"
        # Default to MLX if unknown
        return "mlx"

    def _log_status(self, message, color="black"):
        """Helper to call the status update callback if available."""
        # Only mirror to console if minimal terminal mode is disabled
        try:
            from src.config import config as _cfg
            if not getattr(_cfg, "MINIMAL_TERMINAL_OUTPUT", False):
                print(f"TranscriptionHandler Status: {message}")
        except Exception:
            print(f"TranscriptionHandler Status: {message}")
        if self.on_status_update:
            self.on_status_update(message, color)

    def _transcription_worker_loop(self) -> None:
        """Serial background worker for primary ASR requests."""
        while True:
            if self._transcription_worker_stop.is_set() and self._transcription_queue.empty():
                break
            try:
                item = self._transcription_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                if item is None:
                    break
                audio_data, prompt = item
                self._transcribe_thread_worker(audio_data, prompt)
            finally:
                self._transcription_queue.task_done()

    def shutdown(self) -> None:
        """Stop background worker threads owned by this handler."""
        if not hasattr(self, "_transcription_worker_stop"):
            return

        self._transcription_worker_stop.set()
        try:
            self._transcription_queue.put_nowait(None)
        except queue.Full:
            pass
        worker = getattr(self, "_transcription_worker", None)
        if worker and worker.is_alive():
            worker.join(timeout=2.0)

    def __del__(self):
        try:
            self.shutdown()
        except Exception:
            pass

    def _get_or_load_medasr_pipeline(self, model_path: str):
        """Get MedASR pipeline from cache or create it once."""
        cache_key = str(model_path or self.selected_asr_model or "google/medasr")
        self._log_status(f"Preparing MedASR pipeline: {cache_key}", "grey")
        pipeline, from_cache = self._runtime_manager.get_or_create(
            "medasr",
            cache_key,
            lambda: hf_pipeline(
                "automatic-speech-recognition",
                model=cache_key,
            ),
        )
        self._medasr_pipeline = pipeline
        if from_cache:
            self._log_status(f"Reusing warm MedASR pipeline: {cache_key}", "grey")
        else:
            self._log_status("MedASR pipeline loaded successfully", "grey")
        return pipeline

    def _get_or_load_parakeet_model(self, load_target: str):
        """Get Parakeet model from cache or load it once."""
        if not PARAKEET_MLX_AVAILABLE:
            raise RuntimeError("Parakeet library not available")

        cache_key = str(load_target or self.selected_asr_model)
        self._log_status(f"Preparing Parakeet model: {cache_key}", "grey")
        model, from_cache = self._runtime_manager.get_or_create(
            "parakeet",
            cache_key,
            lambda: parakeet_mlx.from_pretrained(cache_key),
        )
        self.parakeet_model = model
        self._parakeet_loaded_model_id = cache_key
        if from_cache:
            self._log_status(f"Reusing warm Parakeet model: {cache_key}", "grey")
        else:
            self._log_status(f"Parakeet model loaded successfully: {cache_key}", "grey")
        return model

    def _get_or_load_voxtral_model(self, model_path: str):
        """Get Voxtral model from cache or load it once."""
        if not MLX_AUDIO_AVAILABLE:
            raise RuntimeError("mlx-audio library not available")

        cache_key = str(model_path or self.selected_asr_model)
        self._log_status(f"Preparing Voxtral model: {cache_key}", "grey")
        model, from_cache = self._runtime_manager.get_or_create(
            "voxtral",
            cache_key,
            lambda: mlx_audio_generate.load_model(cache_key),
        )
        self.voxtral_model = model
        if from_cache:
            self._log_status(f"Reusing warm Voxtral model: {cache_key}", "grey")
        else:
            self._log_status(f"Voxtral model loaded successfully: {cache_key}", "grey")
        return model

    def _prepare_local_model_copy(self, hf_repo_id: str, *, local_files_only: bool = False) -> str:
        """Ensure a local model copy exists under models/, migrating cache if needed."""
        self._log_status(f"Preparing model locally: {hf_repo_id}", "blue")
        bundled_path = self._get_local_model_dir(hf_repo_id)
        if bundled_path:
            self._log_status(f"Found bundled model at: {bundled_path}", "grey")
            self._ensure_hf_offline_env()
            return bundled_path
        # Target nested directory inside models/, e.g., models/mlx-community/whisper-large-v3-turbo
        target_dir = os.path.join(config.MODELS_ROOT, hf_repo_id.replace("/", os.sep))
        target_parent = os.path.dirname(target_dir)
        try:
            # Ensure models root and nested parent exist
            if not os.path.exists(target_parent):
                os.makedirs(target_parent, exist_ok=True)
                self._log_status(f"Created models directory: {target_parent}", "grey")

            # 1) If already present under models/, use it
            if os.path.isdir(target_dir) and os.path.isfile(os.path.join(target_dir, "config.json")):
                self._log_status(f"Found existing model in models/: {target_dir}", "grey")
                local_model_path = target_dir
            else:
                # 2) Try to migrate from old cache location model_cache_whisper/<repo_underscored>
                legacy_cache_dir = os.path.join(
                    os.path.dirname(config.TEMP_AUDIO_FOLDER),
                    "model_cache_whisper",
                    hf_repo_id.replace("/", "_")
                )
                if os.path.isdir(legacy_cache_dir):
                    # Move legacy cache into models/<org>/<repo>
                    self._log_status(f"Migrating model from cache: {legacy_cache_dir} → {target_dir}", "orange")
                    if os.path.exists(target_dir):
                        shutil.rmtree(target_dir, ignore_errors=True)
                    shutil.move(legacy_cache_dir, target_dir)
                    local_model_path = target_dir
                else:
                    # 3) Download directly into models/
                    if local_files_only or os.getenv("HF_HUB_OFFLINE", "").lower() in {"1", "true", "yes"}:
                        self._log_status(
                            "Download disabled - attempting to use existing local Hugging Face cache",
                            "orange",
                        )
                        try:
                            local_model_path = snapshot_download(
                                repo_id=hf_repo_id,
                                local_dir=target_dir,
                                local_files_only=True,
                            )
                        except LocalEntryNotFoundError as inner_exc:
                            raise RuntimeError(
                                f"Model '{hf_repo_id}' not found in local Hugging Face cache. "
                                "Please download it on a machine with internet access or "
                                f"place the files under '{target_dir}'."
                            ) from inner_exc
                    else:
                        try:
                            local_model_path = snapshot_download(
                                repo_id=hf_repo_id,
                                local_dir=target_dir,
                            )
                        except LocalEntryNotFoundError as inner_exc:
                            raise RuntimeError(
                                f"Failed to download model '{hf_repo_id}'."
                            ) from inner_exc
                    # snapshot_download may return the same local_dir; ensure directory exists
                    if not os.path.isdir(local_model_path):
                        os.makedirs(local_model_path, exist_ok=True)

            self._log_status(f"Model files located at: {local_model_path}", "grey")
        except Exception as e:
            self._log_status(
                f"Error preparing local model for {hf_repo_id}: {e}", "red"
            )
            raise

        # For Whisper models ensure the config.json contains the required dimensions.
        if self._detect_model_type(hf_repo_id) == "whisper":
            self._ensure_whisper_config_integrity(local_model_path, hf_repo_id)

        # Return the local model path without modifying config files
        self._ensure_hf_offline_env()
        return local_model_path

    def ensure_model_assets(self, model_id: str | None = None):
        """Ensure model files are present locally, downloading if necessary."""
        target_model = model_id or self.selected_asr_model
        if not target_model:
            raise ValueError("No model id provided to ensure_model_assets.")

        if self._detect_model_type(target_model) == "apple":
            self._log_status("Apple Speech selected; no model assets to prepare.", "grey")
            return None

        self._log_status(f"Ensuring model assets for: {target_model}", "grey")

        # Respect light mode to avoid heavy downloads
        if getattr(self, "_light_mode", False):
            self._log_status("CT_LIGHT_MODE enabled - skipping model preparation", "orange")
            return None

        # Prefer bundled assets if they already exist
        bundled_path = self._get_local_model_dir(target_model)
        if bundled_path:
            self._log_status(f"Using bundled assets for {target_model}", "grey")
            self._ensure_hf_offline_env()
            return bundled_path

        # Ensure huggingface_hub is available for downloads
        if not HUGGINGFACE_HUB_AVAILABLE:
            raise RuntimeError(
                "huggingface_hub is not installed. Install huggingface-hub>=0.23.0 to download models."
            )

        # Temporarily disable offline mode so snapshot_download can reach Hugging Face
        previous_offline = os.environ.get("HF_HUB_OFFLINE")
        try:
            os.environ["HF_HUB_OFFLINE"] = "0"
            return self._prepare_local_model_copy(target_model, local_files_only=False)
        finally:
            if previous_offline is None:
                os.environ.pop("HF_HUB_OFFLINE", None)
            else:
                os.environ["HF_HUB_OFFLINE"] = previous_offline

    def _ensure_whisper_config_integrity(self, local_model_path: str, hf_repo_id: str) -> None:
        """Validate whisper config.json and repair it if legacy downloads left it empty."""
        config_path = os.path.join(local_model_path, "config.json")
        required_keys = {
            "n_mels",
            "n_audio_ctx",
            "n_audio_state",
            "n_audio_head",
            "n_audio_layer",
            "n_vocab",
            "n_text_ctx",
            "n_text_state",
            "n_text_head",
            "n_text_layer",
        }

        if not os.path.isfile(config_path):
            raise RuntimeError(
                f"Whisper model at '{local_model_path}' is missing config.json. "
                "Re-download the model or copy the config file manually."
            )

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
        except json.JSONDecodeError as err:
            self._log_status(
                f"Whisper config.json unreadable ({err}). Attempting repair…",
                "orange",
            )
            config_data = {}

        if not isinstance(config_data, dict) or not required_keys.issubset(config_data.keys()):
            self._log_status(
                "Whisper config missing model dimensions. Attempting to repair from local Hugging Face cache…",
                "orange",
            )
            if not self._repair_whisper_config_from_cache(hf_repo_id, config_path, required_keys):
                raise RuntimeError(
                    "Unable to repair whisper config.json automatically. "
                    "Delete and re-download the model or copy the config from a known-good environment."
                )

    def _repair_whisper_config_from_cache(
        self,
        hf_repo_id: str,
        target_config_path: str,
        required_keys: set[str],
    ) -> bool:
        """Try to copy a valid config.json from the Hugging Face cache."""
        cache_root = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
        repo_dir = f"models--{hf_repo_id.replace('/', '--')}"
        search_root = os.path.join(cache_root, repo_dir)

        if not os.path.isdir(search_root):
            self._log_status(
                f"No Hugging Face cache found for {hf_repo_id} at {search_root}",
                "red",
            )
            return False

        for root, _, files in os.walk(search_root):
            if "config.json" not in files:
                continue
            candidate_path = os.path.join(root, "config.json")
            try:
                with open(candidate_path, "r", encoding="utf-8") as candidate:
                    candidate_data = json.load(candidate)
            except Exception:
                continue
            if isinstance(candidate_data, dict) and required_keys.issubset(candidate_data.keys()):
                with open(target_config_path, "w", encoding="utf-8") as target:
                    json.dump(candidate_data, target, indent=4)
                    target.write("\n")
                self._log_status(
                    f"Repaired whisper config using cached copy from {candidate_path}",
                    "green",
                )
                return True

        self._log_status(
            f"Failed to locate a valid config.json in Hugging Face cache for {hf_repo_id}",
            "red",
        )
        return False

    def _save_temp_audio(self, audio_data) -> str:
        """Saves audio data to a temporary WAV file."""
        timestamp = int(time.time() * 1000)
        filename = os.path.join(self._temp_folder, f"temp_{timestamp}.wav")
        try:
            with wave.open(filename, "wb") as wf:
                wf.setnchannels(config.CHANNELS)
                # Use pyaudio to get sample width based on the format defined in config
                wf.setsampwidth(pyaudio.get_sample_size(config.AUDIO_FORMAT))
                wf.setframerate(self._sample_rate)
                wf.writeframes(audio_data.tobytes())
            # self._log_status(f"Temporary audio saved: {filename}", "grey") # Optional: Log file saving
            return filename
        except Exception as e:
            self._log_status(
                f"Error saving temporary audio file {filename}: {e}", "red"
            )
            return None  # Indicate failure

    def _load_audio_from_file(self, filename: str):
        """Loads audio data from a WAV file."""
        try:
            with wave.open(filename, "rb") as wf:
                n_frames = wf.getnframes()
                # Assuming audio format is paInt16 as defined in config
                audio = np.frombuffer(wf.readframes(n_frames), dtype=np.int16)
            return audio
        except Exception as e:
            self._log_status(f"Error loading audio file {filename}: {e}", "red")
            return None  # Indicate failure

    def _cleanup_temp_file(self, filename: str):
        """Deletes the temporary audio file."""
        if filename and os.path.exists(filename):
            try:
                os.remove(filename)
                # self._log_status(f"Temporary audio deleted: {filename}", "grey") # Optional: Log file deletion
            except OSError as e:
                self._log_status(
                    f"Error deleting temporary audio file {filename}: {e}", "orange"
                )

    def _build_mlx_whisper_kwargs(self, prompt: str, model_path_or_repo: str) -> dict:
        kwargs = {
            "language": "en",
            "fp16": False,
            "path_or_hf_repo": model_path_or_repo,
        }
        if prompt:
            kwargs["initial_prompt"] = prompt

        transcribe_overrides = getattr(config, "MLX_WHISPER_TRANSCRIBE_OPTIONS", {})
        if isinstance(transcribe_overrides, dict):
            kwargs.update({k: v for k, v in transcribe_overrides.items() if v is not None})

        decode_overrides = getattr(config, "MLX_WHISPER_DECODE_OPTIONS", {})
        if isinstance(decode_overrides, dict):
            kwargs.update({k: v for k, v in decode_overrides.items() if v is not None})

        return kwargs

    def transcribe_audio_data(
        self, audio_data, prompt: str = config.DEFAULT_WHISPER_PROMPT
    ):
        """
        Queue audio for transcription on the long-lived primary ASR worker.

        Args:
            audio_data: Numpy array containing the audio samples.
            prompt: The prompt to guide the transcription (used for Whisper models).
        """
        # Handle mock numpy arrays in CI environment
        if not NUMPY_AVAILABLE and hasattr(audio_data, 'data'):
            # This is a mock array, proceed with mock data
            pass
        elif audio_data is None or (hasattr(audio_data, 'size') and audio_data.size == 0):
            self._log_status("No audio data provided for transcription.", "orange")
            if self.on_transcription_complete:
                self.on_transcription_complete("", 0.0)  # Return empty result
            return

        if not hasattr(self, "_transcription_queue"):
            # Safety fallback for tests that bypass __init__.
            thread = threading.Thread(
                target=self._transcribe_thread_worker,
                args=(audio_data, prompt),
                daemon=True,
            )
            thread.start()
            return

        try:
            self._transcription_queue.put_nowait((audio_data, prompt))
            queued_now = self._transcription_queue.qsize()
            if queued_now > 1:
                self._log_status(
                    f"Primary ASR queue depth: {queued_now}/{self._transcription_queue_size}",
                    "grey",
                )
        except queue.Full:
            self._log_status(
                "Primary ASR queue is full; dropping transcription request to preserve responsiveness.",
                "orange",
            )
            if self.on_transcription_complete:
                self.on_transcription_complete("", 0.0)

    def _transcribe_thread_worker(self, audio_data, prompt: str):
        """Worker function for the transcription thread."""
        self._log_status("Starting transcription process...", "blue")
        filename = None
        raw_text = ""
        transcription_time = 0.0

        try:
            # Check if we're in CI mode (missing dependencies)
            if not MLX_WHISPER_AVAILABLE and not PARAKEET_MLX_AVAILABLE and not MLX_AUDIO_AVAILABLE:
                self._log_status("Transcription mocked - no ASR libraries available (CI environment)", "orange")
                raw_text = "[MOCK TRANSCRIPTION] Test transcription result"
                transcription_time = 0.1  # Mock fast transcription
                log_event(
                    "TRANSCRIBED",
                    "transcription_complete",
                    duration_seconds=round(transcription_time, 2),
                    transcript=raw_text,
                    model=self.selected_asr_model,
                )
                if self.on_transcription_complete:
                    self.on_transcription_complete(raw_text, transcription_time)
                return

            # 1. Save audio to a temporary file
            filename = self._save_temp_audio(audio_data)
            if filename is None:
                self._log_status("Failed to save temporary audio file.", "red")
                return

            # 2. Load audio from file (not strictly necessary, but keeps logic consistent)
            loaded_audio = self._load_audio_from_file(filename)
            if loaded_audio is None:
                self._log_status("Failed to load audio for transcription.", "red")
                return

            # 3. Perform transcription based on model type
            start_time = time.time()
            
            if self.model_type == "apple":
                self._log_status("Using Apple Speech (on-device) for transcription", "blue")
                try:
                    raw_text = self._transcribe_with_apple_speech(filename)
                except Exception as apple_error:
                    self._log_status(
                        f"Apple Speech failed ({apple_error}). Falling back to Whisper…",
                        "orange",
                    )
                    if not MLX_WHISPER_AVAILABLE:
                        raise
                    apple_fallback_kwargs = self._build_mlx_whisper_kwargs(
                        prompt,
                        config.DEFAULT_ASR_MODEL,
                    )
                    result = mlx_whisper.transcribe(filename, **apple_fallback_kwargs)
                    raw_text = (result.get("text", "") or "").strip()

            elif self.model_type == "voxtral":
                self._log_status(f"Using Voxtral (mlx-audio) for transcription with model: {self.selected_asr_model}", "blue")
                if not MLX_AUDIO_AVAILABLE:
                    error_msg = "Voxtral transcription failed - mlx-audio library not installed. Please run: pip install mlx-audio"
                    self._log_status(error_msg, "red")
                    raise RuntimeError(error_msg)

                model_target = self.local_model_path_prepared or self.selected_asr_model
                try:
                    self.voxtral_model = self._get_or_load_voxtral_model(model_target)
                except Exception as model_err:
                    self._log_status(f"Failed to load Voxtral model: {model_err}", "red")
                    raise

                generation_stream = getattr(mlx_audio_generate, "generation_stream", False)
                result = self.voxtral_model.generate(
                    filename,
                    verbose=False,
                    generation_stream=generation_stream,
                    language="en",
                )
                raw_text = getattr(result, "text", "").strip() if result is not None else ""

            elif self.model_type == "medasr":
                self._log_status(f"Using MedASR for transcription with model: {self.selected_asr_model}", "blue")
                if not TRANSFORMERS_AVAILABLE:
                    error_msg = "MedASR transcription failed - transformers library not installed. Please run: pip install transformers"
                    self._log_status(error_msg, "red")
                    raise RuntimeError(error_msg)
                
                try:
                    # Load pipeline (lazy load and cache)
                    # MedASR uses Wav2Vec2/CTC architecture which has incomplete MPS kernel
                    # support in current PyTorch — keep it on CPU where it's stable.
                    model_path = self.local_model_path_prepared or self.selected_asr_model
                    medasr_pipeline = self._get_or_load_medasr_pipeline(model_path)
                    
                    # Run transcription
                    result = medasr_pipeline(
                        filename,
                        chunk_length_s=20,
                        stride_length_s=2
                    )
                    raw_text = result.get("text", "").strip()
                    
                    # Clean up MedASR formatting tokens
                    raw_text = raw_text.replace("{period}", ".").replace("{comma}", ",")
                    raw_text = raw_text.replace("{colon}", ":").replace("{new paragraph}", "\n\n")
                    raw_text = raw_text.replace("</s>", "").strip()
                    
                    self._log_status(f"MedASR transcription complete: {len(raw_text)} chars", "grey")
                    
                except Exception as medasr_error:
                    self._log_status(f"MedASR transcription error: {medasr_error}", "red")
                    raise

            elif self.model_type == "parakeet":
                self._log_status(f"Using Parakeet-MLX for transcription with model: {self.selected_asr_model}", "blue")
                
                if not PARAKEET_MLX_AVAILABLE:
                    # Provide helpful error message instead of mock transcription
                    error_msg = "Parakeet transcription failed"
                    error_msg += " - parakeet_mlx library not installed. Please run: pip install parakeet-mlx"
                    self._log_status(error_msg, "red")
                    raise RuntimeError(error_msg)
                if self.parakeet_model is None:
                    load_target = self.local_model_path_prepared or self.selected_asr_model
                    try:
                        self.parakeet_model = self._get_or_load_parakeet_model(load_target)
                    except Exception as parakeet_load_err:
                        if load_target != self.selected_asr_model:
                            self._log_status(
                                "Parakeet path load failed, retrying with repository id…",
                                "orange",
                            )
                            try:
                                self.parakeet_model = self._get_or_load_parakeet_model(self.selected_asr_model)
                            except Exception as retry_err:
                                error_msg = f"Parakeet transcription failed - model load failed: {retry_err}"
                                self._log_status(error_msg, "red")
                                raise RuntimeError(error_msg) from retry_err
                        else:
                            error_msg = f"Parakeet transcription failed - model load failed: {parakeet_load_err}"
                            self._log_status(error_msg, "red")
                            raise RuntimeError(error_msg) from parakeet_load_err

                # Use parakeet_mlx for transcription
                result = self.parakeet_model.transcribe(filename)
                # Extract text from AlignedResult - use the direct text property
                if hasattr(result, 'text'):
                    raw_text = result.text.strip()
                elif hasattr(result, 'tokens') and result.tokens:
                    # Fallback: concatenate tokens without spaces (character-level tokens)
                    raw_text = ''.join([token.text for token in result.tokens if hasattr(token, 'text')]).strip()
                else:
                    raw_text = str(result).strip()
                    
            else:  # whisper model
                if self._whisper_backend == "transformers":
                    # Use Transformers path directly for non-MLX repos
                    self._log_status(f"Using Transformers-Whisper for transcription with model: {self.selected_asr_model}", "blue")
                    if TRANSFORMERS_AVAILABLE and TORCH_AVAILABLE:
                        raw_text = self._transcribe_with_transformers_whisper(filename, self.selected_asr_model, prompt)
                    else:
                        raise RuntimeError("Transformers/Torch not available for selected Whisper model")
                else:
                    self._log_status(f"Using MLX-Whisper for transcription with model: {self.selected_asr_model}", "blue")
                    if not MLX_WHISPER_AVAILABLE:
                        raw_text = "[MOCK WHISPER TRANSCRIPTION] Test transcription result"
                        self._log_status("Whisper transcription mocked - mlx_whisper not available", "orange")
                    else:
                        # Ensure a valid model path or repo id is available
                        model_path_or_repo = self.local_model_path_prepared or self.selected_asr_model
                        # Do not fallback to Transformers for MLX repos to avoid preprocessor_config.json requirement
                        fallback_attempted = False
                        os.environ.setdefault("HF_HUB_HTTP_TIMEOUT", "5")
                        while True:
                            try:
                                if not model_path_or_repo:
                                    # Last-resort: attempt to prepare local copy now
                                    self.local_model_path_prepared = self._prepare_local_model_copy(self.selected_asr_model)
                                    model_path_or_repo = self.local_model_path_prepared
                                    self._log_status(
                                        f"Prepared Whisper model on-demand at: {model_path_or_repo}",
                                        "grey",
                                    )
                                # Use mlx_whisper for transcription
                                whisper_kwargs = self._build_mlx_whisper_kwargs(
                                    prompt,
                                    model_path_or_repo,
                                )
                                result = mlx_whisper.transcribe(filename, **whisper_kwargs)
                                raw_text = result.get("text", "").strip()
                                break
                            except Exception as whisper_error:
                                if not fallback_attempted:
                                    fallback_attempted = True
                                    self._log_status(
                                        "MLX Whisper reported an error – retrying with local-only model files",
                                        "orange",
                                    )
                                    try:
                                        offline_path = self._prepare_local_model_copy(
                                            self.selected_asr_model,
                                            local_files_only=True,
                                        )
                                    except Exception as offline_error:
                                        self._log_status(
                                            f"Local fallback failed for '{self.selected_asr_model}': {offline_error}",
                                            "red",
                                        )
                                        raise
                                    else:
                                        model_path_or_repo = offline_path
                                        self._ensure_hf_offline_env()
                                        continue
                                self._log_status(
                                    f"MLX Whisper error for '{self.selected_asr_model}': {whisper_error}",
                                    "red",
                                )
                                raise

            end_time = time.time()
            transcription_time = end_time - start_time

            # Apply vocabulary corrections
            try:
                vocab_manager = get_vocabulary_manager()
                corrected_text, corrections = vocab_manager.apply_corrections(raw_text)
                
                if corrections:
                    self._log_status(f"Applied {len(corrections)} vocabulary corrections", "blue")
                    log_event(
                        "VOCAB_CORRECTIONS",
                        "applied_vocabulary_corrections",
                        correction_count=len(corrections),
                    )
                    raw_text = corrected_text
                    
            except Exception as e:
                self._log_status(f"Error applying vocabulary corrections: {e}", "orange")
                # Continue with original text if vocabulary fails
                log_text("VOCAB_ERROR", f"Vocabulary correction failed: {e}")

            log_event(
                "TRANSCRIBED",
                "transcription_complete",
                duration_seconds=round(transcription_time, 2),
                transcript=raw_text,
                model=self.selected_asr_model,
            )
            self._log_status(
                f"Transcription successful ({transcription_time:.2f}s).", "green"
            )

        except Exception as e:
            self._log_status(f"Error during transcription: {e}", "red")
            log_text("TRANSCRIBED", f"(Exception) {str(e)}")
            raw_text = ""  # Ensure empty text on error
            transcription_time = 0.0
        finally:
            # 4. Clean up temporary file
            if filename:
                self._cleanup_temp_file(filename)

            # 5. Call the completion callback (ensure it's thread-safe if it modifies GUI)
            if self.on_transcription_complete:
                # The callback is handled by main.py which uses a queue, so it's safe.
                self.on_transcription_complete(raw_text, transcription_time)

    def _resolve_apple_speech_helper_app(self) -> str | None:
        override = os.getenv("CT_APPLE_SPEECH_HELPER", "").strip()
        if override:
            return os.path.abspath(os.path.expanduser(override))

        # Bundled: extraResources should place AppleSpeechHelper.app alongside the backend in Resources/.
        bundled = config.resolve_resource_path("AppleSpeechHelper.app")
        bundled_abs = os.path.abspath(bundled)
        if os.path.isdir(bundled_abs) and bundled_abs.lower().endswith(".app"):
            return bundled_abs

        # Dev: locate relative to repo root (src/ -> repo/)
        repo_root = Path(__file__).resolve().parents[1]
        dev_app = repo_root / "tools" / "apple_speech_helper" / "dist" / "AppleSpeechHelper.app"
        if dev_app.is_dir():
            return str(dev_app)

        return None

    def _transcribe_with_apple_speech(self, audio_path: str) -> str:
        if platform.system().lower() != "darwin":
            raise RuntimeError("Apple Speech is only available on macOS.")

        helper_app = self._resolve_apple_speech_helper_app()
        if not helper_app:
            raise RuntimeError(
                "AppleSpeechHelper.app not found. Build it with: bash tools/apple_speech_helper/build.sh"
            )

        input_abs = os.path.abspath(audio_path)
        if not os.path.isfile(input_abs):
            raise RuntimeError(f"Audio file not found: {input_abs}")

        debug_keep = os.getenv("CT_APPLE_SPEECH_DEBUG_KEEP", "0") == "1"
        if debug_keep:
            temp_dir = tempfile.mkdtemp(prefix="apple_speech_debug_", dir="/tmp")
            temp_ctx = None
        else:
            temp_ctx = tempfile.TemporaryDirectory(prefix="apple_speech_")
            temp_dir = temp_ctx.name

        try:
            out_json = os.path.join(temp_dir, "out.json")
            done_json = os.path.join(temp_dir, "done.json")

            cmd = [
                "open",
                "-n",
                helper_app,
                "--args",
                "--input-file",
                input_abs,
                "--output-json",
                out_json,
                "--done-file",
                done_json,
                "--locale",
                "en-US",
                "--chunk-seconds",
                os.getenv("CT_APPLE_SPEECH_CHUNK_SECONDS", "20"),
                "--overlap-seconds",
                os.getenv("CT_APPLE_SPEECH_OVERLAP_SECONDS", "1.0"),
                "--timeout-seconds",
                os.getenv("CT_APPLE_SPEECH_TIMEOUT_SECONDS", "60"),
            ]

            # Launch via LaunchServices so macOS can show permissions prompts.
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

            deadline = time.time() + float(os.getenv("CT_APPLE_SPEECH_OVERALL_TIMEOUT_SECONDS", "240"))
            while time.time() < deadline:
                if os.path.exists(done_json):
                    break
                time.sleep(0.05)

            if not os.path.exists(done_json):
                raise RuntimeError("Apple Speech helper did not finish (timeout).")

            try:
                with open(done_json, "r", encoding="utf-8") as f:
                    done = json.load(f)
            except Exception as e:
                raise RuntimeError(f"Apple Speech helper returned unreadable done file: {e}") from e

            exit_code = int(done.get("exit_code", 1))
            if exit_code != 0:
                err = done.get("error") or {}
                code = err.get("code") or "ERROR"
                msg = err.get("message") or "Apple Speech helper failed."
                raise RuntimeError(f"Apple Speech error ({code}): {msg}")

            # Helper should write output before done, but guard against filesystem timing.
            out_deadline = time.time() + 5.0
            while time.time() < out_deadline:
                if os.path.exists(out_json) and os.path.getsize(out_json) > 0:
                    break
                time.sleep(0.05)

            try:
                with open(out_json, "r", encoding="utf-8") as f:
                    out = json.load(f)
            except Exception as e:
                raise RuntimeError(f"Apple Speech helper returned unreadable output: {e}") from e

            if not out.get("success", False):
                code = out.get("code") or "ERROR"
                msg = out.get("message") or "Apple Speech helper failed."
                raise RuntimeError(f"Apple Speech error ({code}): {msg}")

            return (out.get("text") or "").strip()
        finally:
            if temp_ctx is not None:
                temp_ctx.cleanup()

    def retranscribe_audio_file(self, audio_path: str, model_id: str) -> str:
        """
        Transcribe an audio file using a specified ASR model.
        Used for re-transcribing historical audio with different models.
        
        Args:
            audio_path: Path to the WAV audio file
            model_id: Model identifier (e.g., 'google/medasr', 'mlx-community/whisper-large-v3-turbo')
            
        Returns:
            Transcribed text
        """
        self._log_status(f"Re-transcribing with model: {model_id}", "blue")
        
        # Detect model type for this specific model
        model_type = self._detect_model_type(model_id)
        self._log_status(f"Detected model type: {model_type}", "grey")
        
        # Get or prepare local model path
        local_model_path = self._get_local_model_dir(model_id)
        if not local_model_path:
            local_model_path = model_id  # Will try to download/use from HF Hub
        
        # Route to appropriate transcription method based on model type
        if model_type == "medasr":
            return self._retranscribe_with_medasr(audio_path, local_model_path)
        elif model_type == "parakeet":
            return self._retranscribe_with_parakeet(audio_path, local_model_path)
        elif model_type == "voxtral":
            return self._retranscribe_with_voxtral(audio_path, local_model_path)
        elif model_type == "apple":
            return self._transcribe_with_apple_speech(audio_path)
        else:
            # Default to Whisper (MLX or Transformers)
            return self._retranscribe_with_whisper(audio_path, local_model_path, model_id)

    def _retranscribe_with_medasr(self, audio_path: str, model_path: str) -> str:
        """Re-transcribe using MedASR pipeline."""
        if not TRANSFORMERS_AVAILABLE:
            raise RuntimeError("transformers library not available for MedASR")
        
        # Use existing cached pipeline or create new one
        # MedASR uses Wav2Vec2/CTC architecture which has incomplete MPS kernel
        # support in current PyTorch — keep it on CPU where it's stable.
        medasr_pipeline = self._get_or_load_medasr_pipeline(model_path)
        
        result = medasr_pipeline(
            audio_path,
            chunk_length_s=20,
            stride_length_s=2
        )
        raw_text = result.get("text", "").strip()
        
        # Clean up MedASR formatting tokens
        raw_text = raw_text.replace("{period}", ".").replace("{comma}", ",")
        raw_text = raw_text.replace("{colon}", ":").replace("{new paragraph}", "\n\n")
        raw_text = raw_text.replace("</s>", "").strip()
        
        return raw_text

    def _retranscribe_with_parakeet(self, audio_path: str, model_path: str) -> str:
        """Re-transcribe using Parakeet MLX."""
        if not PARAKEET_MLX_AVAILABLE:
            raise RuntimeError("parakeet_mlx library not available")
        
        load_target = model_path or "mlx-community/parakeet-tdt-0.6b-v2"
        
        # Get model from runtime cache (or load once).
        try:
            self.parakeet_model = self._get_or_load_parakeet_model(load_target)
        except Exception as e:
            if load_target != self.selected_asr_model:
                self._log_status(
                    "Parakeet path load failed, retrying with repository id…",
                    "orange",
                )
                try:
                    self.parakeet_model = self._get_or_load_parakeet_model(self.selected_asr_model)
                except Exception as retry_err:
                    self._log_status(f"Failed to load Parakeet model: {retry_err}", "red")
                    raise RuntimeError(
                        f"Failed to load Parakeet model '{self.selected_asr_model}': {retry_err}"
                    ) from retry_err
            else:
                self._log_status(f"Failed to load Parakeet model: {e}", "red")
                raise RuntimeError(f"Failed to load Parakeet model '{load_target}': {e}") from e
        
        self._log_status(f"Transcribing with Parakeet: {audio_path}", "grey")
        result = self.parakeet_model.transcribe(audio_path)
        
        if hasattr(result, 'text'):
            return result.text.strip()
        elif hasattr(result, 'tokens') and result.tokens:
            return ''.join([token.text for token in result.tokens if hasattr(token, 'text')]).strip()
        return str(result).strip()

    def _retranscribe_with_voxtral(self, audio_path: str, model_path: str) -> str:
        """Re-transcribe using Voxtral (mlx-audio)."""
        if not MLX_AUDIO_AVAILABLE:
            raise RuntimeError("mlx-audio library not available")
        
        self.voxtral_model = self._get_or_load_voxtral_model(model_path)
        
        generation_stream = getattr(mlx_audio_generate, "generation_stream", False)
        result = self.voxtral_model.generate(
            audio_path,
            verbose=False,
            generation_stream=generation_stream,
            language="en",
        )
        return getattr(result, "text", "").strip() if result else ""

    def _retranscribe_with_whisper(self, audio_path: str, model_path: str, model_id: str) -> str:
        """Re-transcribe using Whisper (MLX or Transformers)."""
        backend = self._detect_whisper_backend(model_id)
        
        if backend == "transformers" and TRANSFORMERS_AVAILABLE and TORCH_AVAILABLE:
            return self._transcribe_with_transformers_whisper(audio_path, model_path or model_id, "")
        elif MLX_WHISPER_AVAILABLE:
            whisper_kwargs = self._build_mlx_whisper_kwargs("", model_path or model_id)
            result = mlx_whisper.transcribe(audio_path, **whisper_kwargs)
            return result.get("text", "").strip()
        else:
            raise RuntimeError("No Whisper backend available (mlx_whisper or transformers)")

    def _transcribe_with_transformers_whisper(self, audio_path: str, model_id: str, prompt: str) -> str:
        if not (TRANSFORMERS_AVAILABLE and TORCH_AVAILABLE):
            raise RuntimeError("Transformers/Torch not available for Whisper fallback")
        device = "mps" if hasattr(torch.backends, "mps") and torch.backends.mps.is_available() else "cpu"
        torch_dtype = torch.float16 if device == "mps" else torch.float32
        cache_key = f"{model_id}|{device}|{torch_dtype}"

        def _create_pipe():
            processor = AutoProcessor.from_pretrained(model_id)
            model = AutoModelForSpeechSeq2Seq.from_pretrained(
                model_id, torch_dtype=torch_dtype, low_cpu_mem_usage=True
            )
            if device != "cpu":
                model.to(device)
            return hf_pipeline(
                "automatic-speech-recognition",
                model=model,
                tokenizer=processor.tokenizer,
                feature_extractor=processor.feature_extractor,
                torch_dtype=torch_dtype,
                device=0 if device != "cpu" else -1,
            )

        pipe, from_cache = self._runtime_manager.get_or_create(
            "whisper_transformers",
            cache_key,
            _create_pipe,
        )
        if from_cache:
            self._log_status(f"Reusing warm Transformers-Whisper pipeline: {model_id}", "grey")
        # Whisper models typically cap target length at 448 tokens (max_target_positions)
        # Keep a safety margin to account for special/prompt tokens
        safe_max_new_tokens = 440
        gen_kwargs = {
            "max_new_tokens": safe_max_new_tokens,
            "num_beams": 1,
            "condition_on_prev_tokens": False,
        }
        result = pipe(audio_path, generate_kwargs=gen_kwargs)
        return (result.get("text") or "").strip()


# Example Usage (for testing purposes)
if __name__ == "__main__":
    # Assuming utils.py exists with a basic log_text function
    # Create a dummy utils.py if needed:
    # with open("utils.py", "w") as f:
    #     f.write("import time\n")
    #     f.write("def log_text(label, content):\n")
    #     f.write("    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')\n")
    #     f.write("    print(f'{timestamp} [{label}] {content}')\n")
    #     f.write("    # Optionally write to file\n")
    #     f.write("    # with open(config.LOG_FILE, 'a', encoding='utf-8') as log_file:\n")
    #     f.write("    #     log_file.write(f'{timestamp} [{label}] {content}\\n')\n")

    import pyaudio  # Needed for get_sample_size in _save_temp_audio

    def transcription_done(text, duration):
        print("\n--- TRANSCRIPTION COMPLETE ---")
        print(f"Duration: {duration:.2f} seconds")
        print(f"Text: {text}")
        print("----------------------------\n")

    def status_update(message, color):
        print(f"--- STATUS [{color}]: {message} ---")

    print("Initializing TranscriptionHandler...")
    handler = TranscriptionHandler(
        on_transcription_complete_callback=transcription_done,
        on_status_update_callback=status_update,
    )

    # Create a dummy audio signal (e.g., 2 seconds of sine wave)
    sample_rate = config.SAMPLE_RATE
    duration = 2
    frequency = 440  # A4 note
    t = np.linspace(0.0, duration, int(sample_rate * duration))
    amplitude = np.iinfo(np.int16).max * 0.5
    dummy_audio = (amplitude * np.sin(2.0 * np.pi * frequency * t)).astype(np.int16)

    print(f"Created dummy audio: {len(dummy_audio)} samples, dtype={dummy_audio.dtype}")

    print("\nStarting transcription...")
    handler.transcribe_audio_data(dummy_audio)

    print("\nTranscription started in background thread. Waiting...")
    # Keep the main thread alive for a while to let transcription finish
    time.sleep(30)  # Adjust sleep time as needed for the model to run
    print("Test finished.")
