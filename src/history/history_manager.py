import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

class HistoryManager:
    """
    Persists dictation history entries (transcripts + optional audio) to disk.
    Stores newline-delimited JSON records in data/history/history.jsonl and
    audio files under data/history/audio/<id>.wav.
    """

    def __init__(self, base_dir: str = "data/history"):
        self.base_dir = base_dir
        self.audio_dir = os.path.join(self.base_dir, "audio")
        self.history_log = os.path.join(self.base_dir, "history.jsonl")
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        os.makedirs(self.audio_dir, exist_ok=True)
        os.makedirs(self.base_dir, exist_ok=True)
        if not os.path.exists(self.history_log):
            with open(self.history_log, "w", encoding="utf-8") as _:
                pass

    def _write_audio_file(self, entry_id: str, audio_bytes: bytes) -> str:
        audio_path = os.path.join(self.audio_dir, f"{entry_id}.wav")
        with open(audio_path, "wb") as f:
            f.write(audio_bytes)
        return os.path.relpath(audio_path)

    def add_entry(
        self,
        *,
        entry_id: str,
        transcript: str,
        processed_transcript: str,
        duration_seconds: float,
        audio_bytes: Optional[bytes],
        started_at: Optional[float],
        completed_at: Optional[float],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        audio_file_path: Optional[str] = None
        if audio_bytes:
            try:
                audio_file_path = self._write_audio_file(entry_id, audio_bytes)
            except Exception:
                audio_file_path = None

        record = {
            "id": entry_id,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "transcript": transcript or "",
            "processedTranscript": processed_transcript or "",
            "durationSeconds": duration_seconds,
            "audioFile": audio_file_path,
            "startedAt": started_at,
            "completedAt": completed_at,
            "metadata": metadata or {},
        }

        with open(self.history_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        return record
