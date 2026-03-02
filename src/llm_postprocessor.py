#!/usr/bin/env python3
"""
LLM Post-Processor for CitrixTranscriber
Handles optional LLM-based post-processing of transcriptions using LM Studio.
"""

import json
import urllib.request
import urllib.error
from typing import Optional

# LM Studio configuration
LM_STUDIO_BASE_URL = "http://127.0.0.1:1234"
LM_STUDIO_MODEL = "medgemma-4b-it"
TIMEOUT_SECONDS = 10

# Prompt for medical transcription enhancement
MEDICAL_ENHANCEMENT_PROMPT = """You are a medical transcription editor. Your task is to correct any medical terminology errors in the transcription below without changing its meaning, structure, or style.

Rules:
- Fix misspelled medical terms, drug names, and dosages
- Do not add or remove information
- Do not change the conversational tone
- Return ONLY the corrected text with no explanation

Transcription to correct:
"""


def is_lm_studio_available() -> bool:
    """Check if LM Studio is running and accessible."""
    try:
        req = urllib.request.Request(
            f"{LM_STUDIO_BASE_URL}/v1/models",
            method="GET"
        )
        with urllib.request.urlopen(req, timeout=2) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def enhance_medical_transcription(text: str) -> str:
    """
    Enhance medical transcription using LM Studio's MedGemma model.
    
    Args:
        text: Raw transcription text
        
    Returns:
        Enhanced text, or original text if LM Studio is unavailable
    """
    if not text or not text.strip():
        return text
    
    try:
        payload = {
            "model": LM_STUDIO_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": MEDICAL_ENHANCEMENT_PROMPT + text
                }
            ],
            "temperature": 0.1,  # Low temperature for deterministic output
            "max_tokens": len(text) * 2,  # Allow some expansion for corrections
        }
        
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{LM_STUDIO_BASE_URL}/v1/chat/completions",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
            enhanced_text = result["choices"][0]["message"]["content"].strip()
            
            # Basic sanity check: if response is dramatically different length, use original
            if len(enhanced_text) < len(text) * 0.3 or len(enhanced_text) > len(text) * 3:
                _log_warning(f"LLM response length mismatch, using original text")
                return text
            
            _log_info(f"Enhanced transcription via MedGemma")
            return enhanced_text
            
    except urllib.error.URLError as e:
        _log_warning(f"LM Studio not available: {e}")
        return text
    except TimeoutError:
        _log_warning("LM Studio request timed out")
        return text
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        _log_warning(f"Failed to parse LM Studio response: {e}")
        return text
    except Exception as e:
        _log_warning(f"Unexpected error in LLM post-processing: {e}")
        return text


def _log_info(message: str) -> None:
    """Log info message respecting terminal output settings."""
    try:
        from src.utils.utils import log_text
        log_text("LLM_POST", message, color="cyan")
    except Exception:
        pass  # Silently fail if logging not available


def _log_warning(message: str) -> None:
    """Log warning message respecting terminal output settings."""
    try:
        from src.utils.utils import log_text
        log_text("LLM_WARN", message, color="yellow")
    except Exception:
        pass  # Silently fail if logging not available
