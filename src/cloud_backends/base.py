"""Abstract base class for cloud ASR backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from src.transcript_model import TranscriptResult


class CloudASRBackend(ABC):
    """Base interface for cloud-based ASR backends."""

    @abstractmethod
    def transcribe(
        self,
        audio_path: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> TranscriptResult:
        """Transcribe an audio file and return a structured result.

        Args:
            audio_path: Path to the audio file.
            options: Backend-specific options (language, diarization, etc.).

        Returns:
            A TranscriptResult with the transcription.
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this backend's API key/credentials are configured."""
        ...
