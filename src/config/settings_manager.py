#!/usr/bin/env python3
"""
Settings Manager for OpenScribe
Handles saving and loading user preferences between sessions.
"""

import json
import os
from typing import Dict, Any

from src.config import config
from src import settings_contract

class SettingsManager:
    """Manages user settings persistence."""
    
    def __init__(self, settings_file: str = "user_settings.json"):
        """
        Initialize the settings manager.
        
        Args:
            settings_file: Path to the settings file
        """
        self.settings_file = settings_file
        self.settings = self._load_default_settings()
        self.load_settings()
    
    def _load_default_settings(self) -> Dict[str, Any]:
        """Load default settings from config."""
        defaults = dict(settings_contract.PYTHON_DEFAULTS)
        defaults["selectedAsrModel"] = str(
            defaults.get("selectedAsrModel") or config.DEFAULT_ASR_MODEL
        )
        defaults["programActive"] = bool(defaults.get("programActive", True))
        wake_words_default = defaults.get("wakeWords")
        defaults["wakeWords"] = wake_words_default if isinstance(wake_words_default, dict) else config.WAKE_WORDS
        defaults["wakeWordEnabled"] = bool(defaults.get("wakeWordEnabled", True))
        defaults["filterFillerWords"] = bool(defaults.get("filterFillerWords", True))
        filler_words_default = defaults.get("fillerWords")
        if not isinstance(filler_words_default, list):
            filler_words_default = ["um", "uh", "ah", "er", "hmm", "mm", "mhm"]
        defaults["fillerWords"] = list(filler_words_default)
        defaults["autoStopOnSilence"] = bool(defaults.get("autoStopOnSilence", True))
        defaults["useMedGemmaPostProcessing"] = bool(
            defaults.get("useMedGemmaPostProcessing", False)
        )
        defaults["secondaryAsrModel"] = defaults.get("secondaryAsrModel")
        defaults["medicationAutoLearnEnabled"] = bool(
            defaults.get("medicationAutoLearnEnabled", True)
        )
        defaults["selectedMicrophoneId"] = str(defaults.get("selectedMicrophoneId", "default"))
        defaults["transcribeShortcut"] = str(defaults.get("transcribeShortcut", "Option+Space"))
        defaults["stopTranscribingShortcut"] = str(
            defaults.get("stopTranscribingShortcut", "Cmd+Shift+S")
        )
        defaults["retranscribeBackupShortcut"] = str(
            defaults.get("retranscribeBackupShortcut", "Ctrl+Option+R")
        )
        return defaults
    
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
        
        # Ensure new settings keys exist with sane defaults
        wake_words = self.settings.get("wakeWords")
        if isinstance(wake_words, dict):
            dictate_words = wake_words.get("dictate", [])
            if not isinstance(dictate_words, list):
                dictate_words = []
            self.settings["wakeWords"] = {"dictate": dictate_words}
        else:
            self.settings["wakeWords"] = {"dictate": config.WAKE_WORDS.get("dictate", [])}
        if "wakeWordEnabled" not in self.settings:
            self.settings["wakeWordEnabled"] = True
        if "medicationAutoLearnEnabled" not in self.settings:
            self.settings["medicationAutoLearnEnabled"] = True

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
        if save:
            self.save_settings()
    
    def get_all_settings(self) -> Dict[str, Any]:
        """Get all current settings."""
        return self.settings.copy()


# Global settings manager instance
settings_manager = SettingsManager() 
