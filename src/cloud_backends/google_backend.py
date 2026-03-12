"""Google Cloud Speech / Chirp 2 cloud ASR backend."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from src.transcript_model import TranscriptResult, TranscriptSegment
from src.cloud_backends.base import CloudASRBackend

try:
    from google.cloud import speech_v2
    from google.cloud.speech_v2 import types as speech_types
    GOOGLE_SPEECH_AVAILABLE = True
except ImportError:
    GOOGLE_SPEECH_AVAILABLE = False
    speech_v2 = None  # type: ignore
    speech_types = None  # type: ignore


class GoogleBackend(CloudASRBackend):
    """Google Cloud Speech-to-Text v2 / Chirp 2 backend."""

    def __init__(self, key_path: Optional[str] = None, project_id: Optional[str] = None):
        self._key_path = key_path
        self._project_id = project_id

    def is_available(self) -> bool:
        if not GOOGLE_SPEECH_AVAILABLE:
            return False
        return bool(self._key_path and os.path.isfile(self._key_path))

    def transcribe(
        self,
        audio_path: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> TranscriptResult:
        if not GOOGLE_SPEECH_AVAILABLE:
            raise RuntimeError(
                "google-cloud-speech is not installed. "
                "Install it with: pip install google-cloud-speech"
            )
        if not self._key_path or not os.path.isfile(self._key_path):
            raise RuntimeError("Google Cloud key file is not configured or not found.")

        opts = options or {}
        language = opts.get("language", "en-US")
        diarization = opts.get("diarization", False)

        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self._key_path

        with open(audio_path, "rb") as audio_file:
            audio_content = audio_file.read()

        client = speech_v2.SpeechClient()
        project_id = self._project_id or self._extract_project_id()

        recognition_features = {}
        if diarization:
            recognition_features["diarization_config"] = speech_types.SpeakerDiarizationConfig(
                enable_speaker_diarization=True,
                min_speaker_count=1,
                max_speaker_count=6,
            )

        config = speech_types.RecognitionConfig(
            auto_decoding_config=speech_types.AutoDetectDecodingConfig(),
            language_codes=[language],
            model="chirp_2",
            features=speech_types.RecognitionFeatures(**recognition_features) if recognition_features else None,
        )

        request = speech_types.RecognizeRequest(
            recognizer=f"projects/{project_id}/locations/global/recognizers/_",
            config=config,
            content=audio_content,
        )

        response = client.recognize(request=request)

        full_text_parts = []
        segments = []
        for result in response.results:
            if not result.alternatives:
                continue
            alt = result.alternatives[0]
            text = alt.transcript.strip()
            if text:
                full_text_parts.append(text)

            if diarization and hasattr(alt, "words"):
                for word_info in alt.words:
                    speaker_label = f"Speaker {word_info.speaker_label}" if hasattr(word_info, "speaker_label") and word_info.speaker_label else None
                    start_sec = word_info.start_offset.total_seconds() if hasattr(word_info.start_offset, "total_seconds") else None
                    end_sec = word_info.end_offset.total_seconds() if hasattr(word_info.end_offset, "total_seconds") else None
                    segments.append(
                        TranscriptSegment(
                            text=word_info.word,
                            start=start_sec,
                            end=end_sec,
                            speaker=speaker_label,
                        )
                    )

        full_text = " ".join(full_text_parts)
        return TranscriptResult(
            full_text=full_text,
            segments=segments,
            language=language,
            duration_seconds=None,
            model_id="google:chirp_2",
            diarization_enabled=diarization,
        )

    def _extract_project_id(self) -> str:
        """Try to extract project ID from the service account key file."""
        if not self._key_path:
            raise RuntimeError("Google Cloud key path not set.")
        import json
        try:
            with open(self._key_path, "r", encoding="utf-8") as f:
                key_data = json.load(f)
            project_id = key_data.get("project_id")
            if project_id:
                return project_id
        except Exception:
            pass
        raise RuntimeError(
            "Could not determine Google Cloud project ID. "
            "Set it in your service account key file or provide it explicitly."
        )
