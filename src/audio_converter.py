"""Audio format conversion utilities for file-based transcription.

Converts mp3/m4a/webm/mp4 to WAV 16kHz mono for local ASR backends.
Cloud backends accept originals directly.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

# Conditional import following project pattern
try:
    from pydub import AudioSegment
    from pydub.utils import which
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    AudioSegment = None  # type: ignore

SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".webm", ".mp4", ".ogg", ".flac"}


def is_ffmpeg_available() -> bool:
    """Check if ffmpeg is available on the system PATH."""
    if not PYDUB_AVAILABLE:
        return False
    return which("ffmpeg") is not None


def is_supported_format(file_path: str) -> bool:
    """Return True if the file extension is a supported audio format."""
    ext = Path(file_path).suffix.lower()
    return ext in SUPPORTED_EXTENSIONS


def get_audio_duration(file_path: str) -> Optional[float]:
    """Return the duration of an audio file in seconds, or None on failure."""
    if not PYDUB_AVAILABLE:
        return None
    try:
        audio = AudioSegment.from_file(file_path)
        return len(audio) / 1000.0
    except Exception:
        return None


def convert_to_wav_16k(input_path: str, output_dir: Optional[str] = None) -> str:
    """Convert an audio file to WAV 16kHz mono.

    Args:
        input_path: Path to the source audio file.
        output_dir: Directory for the output file. Uses a temp dir if None.

    Returns:
        Path to the converted WAV file.

    Raises:
        RuntimeError: If pydub or ffmpeg is not available.
        FileNotFoundError: If the input file does not exist.
    """
    if not PYDUB_AVAILABLE:
        raise RuntimeError(
            "pydub is not installed. Install it with: pip install pydub"
        )
    if not is_ffmpeg_available():
        raise RuntimeError(
            "ffmpeg is not found on the system PATH. "
            "Install ffmpeg to enable audio conversion."
        )
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Audio file not found: {input_path}")

    ext = Path(input_path).suffix.lower()
    # If already a 16kHz mono WAV, return as-is
    if ext == ".wav":
        try:
            audio = AudioSegment.from_wav(input_path)
            if audio.frame_rate == 16000 and audio.channels == 1:
                return input_path
        except Exception:
            pass

    audio = AudioSegment.from_file(input_path)
    audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)

    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="openscribe_conv_")
    stem = Path(input_path).stem
    output_path = os.path.join(output_dir, f"{stem}_16k.wav")
    audio.export(output_path, format="wav")
    return output_path
