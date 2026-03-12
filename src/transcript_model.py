"""Canonical structured transcript result that all ASR backends normalize into."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class TranscriptSegment:
    """A single segment of a transcript with optional timing and speaker info."""
    text: str
    start: Optional[float] = None  # seconds
    end: Optional[float] = None
    speaker: Optional[str] = None  # "Speaker 1", etc.


@dataclass
class TranscriptResult:
    """Complete structured transcript from any ASR backend."""
    full_text: str
    segments: List[TranscriptSegment] = field(default_factory=list)
    language: Optional[str] = None
    duration_seconds: Optional[float] = None
    model_id: Optional[str] = None
    diarization_enabled: bool = False

    def to_plain_text(self) -> str:
        """Return the transcript as plain text without speaker labels."""
        return self.full_text

    def to_diarized_text(self) -> str:
        """Return transcript with speaker labels if diarization was enabled."""
        if not self.diarization_enabled or not self.segments:
            return self.full_text

        lines = []
        current_speaker = None
        current_texts = []

        for segment in self.segments:
            speaker = segment.speaker or "Unknown"
            if speaker != current_speaker:
                if current_texts:
                    lines.append(f"{current_speaker}: {' '.join(current_texts)}")
                current_speaker = speaker
                current_texts = [segment.text]
            else:
                current_texts.append(segment.text)

        if current_texts and current_speaker:
            lines.append(f"{current_speaker}: {' '.join(current_texts)}")

        return "\n\n".join(lines) if lines else self.full_text

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dictionary."""
        return {
            "fullText": self.full_text,
            "segments": [
                {
                    "text": s.text,
                    "start": s.start,
                    "end": s.end,
                    "speaker": s.speaker,
                }
                for s in self.segments
            ],
            "language": self.language,
            "durationSeconds": self.duration_seconds,
            "modelId": self.model_id,
            "diarizationEnabled": self.diarization_enabled,
        }
