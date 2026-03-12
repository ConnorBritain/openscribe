"""Transcript formatting utilities for export."""

from __future__ import annotations

from typing import Optional

from src.transcript_model import TranscriptResult


def format_transcript(
    result: TranscriptResult,
    *,
    include_speakers: bool = False,
    include_timestamps: bool = False,
) -> str:
    """Format a TranscriptResult for export.

    Args:
        result: The transcript result to format.
        include_speakers: Include speaker labels if available.
        include_timestamps: Include segment timestamps if available.

    Returns:
        Formatted transcript string.
    """
    if include_speakers and result.diarization_enabled:
        return result.to_diarized_text()

    if include_timestamps and result.segments:
        lines = []
        for seg in result.segments:
            prefix = ""
            if seg.start is not None:
                minutes = int(seg.start // 60)
                seconds = seg.start % 60
                prefix = f"[{minutes:02d}:{seconds:05.2f}] "
            if include_speakers and seg.speaker:
                prefix += f"{seg.speaker}: "
            lines.append(f"{prefix}{seg.text}")
        return "\n".join(lines)

    return result.to_plain_text()
