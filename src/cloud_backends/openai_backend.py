"""OpenAI Whisper / GPT-4o Transcribe cloud ASR backend."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from src.transcript_model import TranscriptResult, TranscriptSegment
from src.cloud_backends.base import CloudASRBackend

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    httpx = None  # type: ignore

# 25 MB limit for OpenAI audio API
OPENAI_MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024

OPENAI_SUPPORTED_FORMATS = {".mp3", ".wav", ".m4a", ".webm", ".mp4", ".mpeg", ".mpga", ".oga", ".ogg", ".flac"}


class OpenAIBackend(CloudASRBackend):
    """OpenAI Whisper / GPT-4o Transcribe backend using the REST API."""

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key

    def is_available(self) -> bool:
        if not HTTPX_AVAILABLE:
            return False
        return bool(self._api_key)

    def transcribe(
        self,
        audio_path: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> TranscriptResult:
        if not HTTPX_AVAILABLE:
            raise RuntimeError("httpx is not installed. Install it with: pip install httpx")
        if not self._api_key:
            raise RuntimeError("OpenAI API key is not configured.")

        opts = options or {}
        model = opts.get("model", "whisper-1")
        language = opts.get("language", "en")

        file_size = os.path.getsize(audio_path)
        if file_size > OPENAI_MAX_FILE_SIZE_BYTES:
            raise ValueError(
                f"File size ({file_size / (1024 * 1024):.1f} MB) exceeds "
                f"OpenAI's 25 MB limit. Use a local model or compress the file."
            )

        file_name = os.path.basename(audio_path)
        with open(audio_path, "rb") as audio_file:
            files = {"file": (file_name, audio_file)}
            data = {
                "model": model,
                "response_format": "verbose_json",
                "language": language,
            }

            with httpx.Client(timeout=300.0) as client:
                response = client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    files=files,
                    data=data,
                )

        if response.status_code == 401:
            raise RuntimeError("Invalid OpenAI API key. Check your key in Settings.")
        response.raise_for_status()

        result_json = response.json()
        full_text = result_json.get("text", "").strip()
        duration = result_json.get("duration")
        detected_language = result_json.get("language", language)

        segments = []
        for seg in result_json.get("segments", []):
            segments.append(
                TranscriptSegment(
                    text=seg.get("text", "").strip(),
                    start=seg.get("start"),
                    end=seg.get("end"),
                    speaker=None,  # OpenAI doesn't provide diarization
                )
            )

        return TranscriptResult(
            full_text=full_text,
            segments=segments,
            language=detected_language,
            duration_seconds=duration,
            model_id=f"openai:{model}",
            diarization_enabled=False,
        )
