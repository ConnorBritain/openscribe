#!/usr/bin/env python3
"""
Settings Manager for CitrixTranscriber
Handles saving and loading user preferences between sessions.
"""

import json
import os
import sys
from typing import Dict, Any, Optional
from src.config import config
from packaging import version

try:
    from importlib import metadata as importlib_metadata
except ImportError:  # pragma: no cover - Python <3.8 compatibility shim
    import importlib_metadata  # type: ignore

class SettingsManager:
    """Manages user settings persistence."""
    
    def __init__(self, settings_file: str = "user_settings.json"):
        """
        Initialize the settings manager.
        
        Args:
            settings_file: Path to the settings file
        """
        self.settings_file = settings_file
        self._cached_mlx_lm_version: Optional[str] = None
        self.settings = self._load_default_settings()
        self.load_settings()
    
    def _load_default_settings(self) -> Dict[str, Any]:
        """Load default settings from config."""
        return {
            "selectedAsrModel": config.DEFAULT_ASR_MODEL,
            "selectedProofingModel": config.DEFAULT_LLM,
            "selectedLetterModel": config.DEFAULT_LLM,
            "programActive": True,
            "wakeWords": config.WAKE_WORDS,
            "proofingPrompt": config.DEFAULT_PROOFREAD_PROMPT,
            "letterPrompt": config.DEFAULT_LETTER_PROMPT,
            "filterFillerWords": True,  # New setting for filler word filtering
            "fillerWords": ["um", "uh", "ah", "er", "hmm", "mm", "mhm"]  # Default filler words
        }

    def _get_installed_mlx_lm_version(self) -> Optional[str]:
        if self._cached_mlx_lm_version is not None:
            return self._cached_mlx_lm_version

        try:
            module = sys.modules.get("mlx_lm")
            if module:
                detected = getattr(module, "__version__", None)
                if detected:
                    self._cached_mlx_lm_version = str(detected)
                    return self._cached_mlx_lm_version
        except Exception:
            pass

        try:
            self._cached_mlx_lm_version = importlib_metadata.version("mlx-lm")
        except importlib_metadata.PackageNotFoundError:
            self._cached_mlx_lm_version = None
        except Exception:
            self._cached_mlx_lm_version = None
        return self._cached_mlx_lm_version

    @staticmethod
    def _resolve_llm_key(model_id: Optional[str]) -> Optional[str]:
        if not model_id:
            return None
        for key, value in getattr(config, "AVAILABLE_LLMS", {}).items():
            if value == model_id:
                return key
        return None

    def _sanitize_llm_selection(self, settings_key: str) -> None:
        model_id = self.settings.get(settings_key)
        available_ids = set(getattr(config, "AVAILABLE_LLMS", {}).values())
        if not model_id or model_id not in available_ids:
            fallback_id = config.DEFAULT_LLM
            if self.settings.get(settings_key) != fallback_id:
                self.settings[settings_key] = fallback_id
            return

        model_key = self._resolve_llm_key(model_id)
        if not model_key:
            fallback_id = config.DEFAULT_LLM
            if self.settings.get(settings_key) != fallback_id:
                self.settings[settings_key] = fallback_id
            return

        min_versions = getattr(config, "LLM_MIN_MLX_LM_VERSION", {})
        min_required = min_versions.get(model_key)
        if not min_required:
            return

        installed = self._get_installed_mlx_lm_version()
        try:
            meets_requirement = (
                installed is not None
                and version.parse(str(installed)) >= version.parse(str(min_required))
            )
        except Exception:
            meets_requirement = False

        if meets_requirement:
            return

        fallback_id = config.DEFAULT_LLM
        if self.settings.get(settings_key) == fallback_id:
            return

        self.settings[settings_key] = fallback_id
        message = (
            f"[Settings] '{model_key}' requires mlx-lm {min_required}+ "
            f"(detected {installed or 'none'}). Falling back to default model."
        )
        try:
            from src.config import config as _cfg  # Lazy import for MINIMAL_TERMINAL_OUTPUT
            if not getattr(_cfg, "MINIMAL_TERMINAL_OUTPUT", False):
                print(message)
        except Exception:
            print(message)
    
    def load_settings(self) -> Dict[str, Any]:
        """
        Load settings from file.
        
        Returns:
            Dictionary of loaded settings
        """
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    saved_settings = json.load(f)
                    # Merge with defaults to ensure all keys exist
                    self.settings.update(saved_settings)
                    # Migrate deprecated/removed ASR models to the default stable model
                    deprecated_asr_ids = {
                        "Bhaveen/Medical-Speech-Transcription-Whisper-Small-Fine-Tuned",
                        "distil-whisper/distil-large-v3",
                        "Na0s/Medical-Whisper-Large-v3",
                    }
                    if self.settings.get("selectedAsrModel") in deprecated_asr_ids:
                        self.settings["selectedAsrModel"] = config.DEFAULT_ASR_MODEL
                        try:
                            from src.config import config as _cfg
                            if not getattr(_cfg, "MINIMAL_TERMINAL_OUTPUT", False):
                                print(f"[Settings] Migrated selectedAsrModel to '{config.DEFAULT_ASR_MODEL}'")
                        except Exception:
                            print(f"[Settings] Migrated selectedAsrModel to '{config.DEFAULT_ASR_MODEL}'")
                    # Sanitize empty or invalid ASR model
                    asr_id = self.settings.get("selectedAsrModel")
                    valid_asr_ids = set(getattr(config, "AVAILABLE_ASR_MODELS", {}).values())
                    if not asr_id or (valid_asr_ids and asr_id not in valid_asr_ids):
                        self.settings["selectedAsrModel"] = config.DEFAULT_ASR_MODEL
                    # Ensure LLM selections remain valid with current installation
                    self._sanitize_llm_selection("selectedProofingModel")
                    self._sanitize_llm_selection("selectedLetterModel")
                    try:
                        from src.config import config as _cfg
                        if not getattr(_cfg, "MINIMAL_TERMINAL_OUTPUT", False):
                            print(f"[Settings] Loaded from {self.settings_file}")
                    except Exception:
                        print(f"[Settings] Loaded from {self.settings_file}")
            except (json.JSONDecodeError, IOError) as e:
                try:
                    from src.config import config as _cfg
                    if not getattr(_cfg, "MINIMAL_TERMINAL_OUTPUT", False):
                        print(f"[Settings] Error loading {self.settings_file}: {e}")
                        print(f"[Settings] Using default settings")
                except Exception:
                    print(f"[Settings] Error loading {self.settings_file}: {e}")
                    print(f"[Settings] Using default settings")
        else:
            try:
                from src.config import config as _cfg
                if not getattr(_cfg, "MINIMAL_TERMINAL_OUTPUT", False):
                    print(f"[Settings] No settings file found, using defaults")
            except Exception:
                print(f"[Settings] No settings file found, using defaults")
        
        return self.settings
    
    def save_settings(self) -> bool:
        """
        Save current settings to file.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(os.path.abspath(self.settings_file)), exist_ok=True)
            
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
            try:
                from src.config import config as _cfg
                if not getattr(_cfg, "MINIMAL_TERMINAL_OUTPUT", False):
                    print(f"[Settings] Saved to {self.settings_file}")
            except Exception:
                print(f"[Settings] Saved to {self.settings_file}")
            return True
        except IOError as e:
            try:
                from src.config import config as _cfg
                if not getattr(_cfg, "MINIMAL_TERMINAL_OUTPUT", False):
                    print(f"[Settings] Error saving {self.settings_file}: {e}")
            except Exception:
                print(f"[Settings] Error saving {self.settings_file}: {e}")
            return False
    
    def get_setting(self, key: str, default: Any = None) -> Any:
        """
        Get a setting value.
        
        Args:
            key: Setting key
            default: Default value if key not found
            
        Returns:
            Setting value or default
        """
        return self.settings.get(key, default)
    
    def set_setting(self, key: str, value: Any, save: bool = True) -> None:
        """
        Set a setting value.
        
        Args:
            key: Setting key
            value: Setting value
            save: Whether to save to file immediately
        """
        self.settings[key] = value
        if key in {"selectedProofingModel", "selectedLetterModel"}:
            self._sanitize_llm_selection(key)
        if save:
            self.save_settings()
    
    def update_settings(self, new_settings: Dict[str, Any], save: bool = True) -> None:
        """
        Update multiple settings.
        
        Args:
            new_settings: Dictionary of settings to update
            save: Whether to save to file immediately
        """
        self.settings.update(new_settings)
        for key in ("selectedProofingModel", "selectedLetterModel"):
            if key in new_settings:
                self._sanitize_llm_selection(key)
        if save:
            self.save_settings()
    
    def get_all_settings(self) -> Dict[str, Any]:
        """Get all current settings."""
        return self.settings.copy()


# Global settings manager instance
settings_manager = SettingsManager() 
