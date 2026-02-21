import threading
import time
import uuid
from collections import deque
from typing import Any, Dict, Optional

from src.utils.utils import log_text


class DictationSessionStore:
    """Tracks API dictation sessions and recent results."""

    def __init__(self, *, max_results: int = 50, ttl_seconds: int = 900):
        self._lock = threading.Lock()
        self._max_results = max(1, int(max_results))
        self._ttl_seconds = max(60, int(ttl_seconds))
        self._active_session_id: Optional[str] = None
        self._active_session_started_at: Optional[float] = None
        self._active_session_suppress_paste = False
        self._last_completed_session_id: Optional[str] = None
        self._latest_audio_amp = 0
        self._session_results: Dict[str, Dict[str, Any]] = {}
        self._session_result_order = deque()

    @staticmethod
    def _empty_result(session_id: str) -> Dict[str, Any]:
        return {
            "success": True,
            "sessionId": session_id,
            "state": "not_found",
            "processedTranscript": "",
            "historyEntryId": None,
            "completedAt": None,
        }

    @staticmethod
    def _clamp_audio_amp(value: int) -> int:
        return max(0, min(100, int(value)))

    @staticmethod
    def _is_transition_allowed(current_state: Optional[str], next_state: str) -> bool:
        if current_state in (None, next_state):
            return True
        if current_state == "dictation":
            return next_state in {"processing", "complete", "not_found"}
        if current_state == "processing":
            return next_state in {"complete", "not_found"}
        if current_state in {"complete", "not_found"}:
            return False
        return False

    def _ensure_session_record_locked(self, session_id: str, now: float) -> Dict[str, Any]:
        record = self._session_results.get(session_id)
        if record is None:
            record = {
                "sessionId": session_id,
                "state": "dictation",
                "processedTranscript": "",
                "historyEntryId": None,
                "completedAt": None,
                "startedAt": None,
                "source": None,
                "lastUpdatedAt": now,
            }
            self._session_results[session_id] = record
            self._session_result_order.append(session_id)
        record["lastUpdatedAt"] = now
        return record

    def _transition_state_locked(self, record: Dict[str, Any], next_state: str) -> None:
        current_state = record.get("state")
        if not self._is_transition_allowed(current_state, next_state):
            log_text(
                "SESSION",
                f"Ignoring invalid session transition {current_state} -> {next_state} for {record.get('sessionId')}",
            )
            return
        record["state"] = next_state

    def _evict_stale_locked(self, now: float) -> None:
        stale_ids = [
            session_id
            for session_id, record in self._session_results.items()
            if session_id != self._active_session_id
            and (now - float(record.get("lastUpdatedAt") or now)) > self._ttl_seconds
        ]
        if stale_ids:
            stale_set = set(stale_ids)
            for stale_id in stale_ids:
                self._session_results.pop(stale_id, None)
            self._session_result_order = deque(
                session_id for session_id in self._session_result_order if session_id not in stale_set
            )

        while len(self._session_result_order) > self._max_results:
            oldest = self._session_result_order.popleft()
            if oldest == self._active_session_id:
                self._session_result_order.append(oldest)
                if len(self._session_result_order) <= 1:
                    break
                continue
            self._session_results.pop(oldest, None)

    def begin_session(self, *, suppress_paste: bool = False, source: Optional[str] = None) -> str:
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        now = time.time()
        with self._lock:
            self._evict_stale_locked(now)
            self._active_session_id = session_id
            self._active_session_started_at = now
            self._active_session_suppress_paste = bool(suppress_paste)
            self._latest_audio_amp = 0
            record = self._ensure_session_record_locked(session_id, now)
            self._transition_state_locked(record, "dictation")
            record.update(
                {
                    "processedTranscript": "",
                    "historyEntryId": None,
                    "completedAt": None,
                    "startedAt": now,
                    "source": source,
                    "lastUpdatedAt": now,
                }
            )
        return session_id

    def clear_active(self, *, as_not_found: bool = False) -> None:
        now = time.time()
        with self._lock:
            session_id = self._active_session_id
            if session_id and as_not_found:
                record = self._ensure_session_record_locked(session_id, now)
                self._transition_state_locked(record, "not_found")
                record.update(
                    {
                        "processedTranscript": "",
                        "historyEntryId": None,
                        "completedAt": now,
                        "lastUpdatedAt": now,
                    }
                )
            self._active_session_id = None
            self._active_session_started_at = None
            self._active_session_suppress_paste = False
            self._evict_stale_locked(now)

    def mark_processing(self) -> Optional[str]:
        now = time.time()
        with self._lock:
            session_id = self._active_session_id
            if not session_id:
                return None
            record = self._ensure_session_record_locked(session_id, now)
            if record.get("state") != "complete":
                self._transition_state_locked(record, "processing")
                record["lastUpdatedAt"] = now
            self._evict_stale_locked(now)
            return session_id

    def complete_active(
        self, *, processed_text: str, history_entry_id: Optional[str], completed_at: Optional[float]
    ) -> Dict[str, Any]:
        now = time.time()
        with self._lock:
            session_id = self._active_session_id
            suppress_paste = self._active_session_suppress_paste
            if session_id:
                record = self._ensure_session_record_locked(session_id, now)
                self._transition_state_locked(record, "complete")
                record.update(
                    {
                        "processedTranscript": processed_text or "",
                        "historyEntryId": history_entry_id,
                        "completedAt": completed_at if completed_at is not None else now,
                        "lastUpdatedAt": now,
                    }
                )
                self._last_completed_session_id = session_id

            self._active_session_id = None
            self._active_session_started_at = None
            self._active_session_suppress_paste = False
            self._evict_stale_locked(now)

        return {"sessionId": session_id, "suppressPaste": suppress_paste}

    def is_stop_session_valid(self, session_id: Optional[str]) -> bool:
        if not session_id:
            return True
        with self._lock:
            return bool(self._active_session_id) and self._active_session_id == session_id

    def set_audio_amp(self, amp_value: int) -> None:
        now = time.time()
        with self._lock:
            self._latest_audio_amp = self._clamp_audio_amp(amp_value)
            self._evict_stale_locked(now)

    def get_status_snapshot(self) -> Dict[str, Any]:
        now = time.time()
        with self._lock:
            self._evict_stale_locked(now)
            return {
                "audioLevel": int(self._latest_audio_amp or 0),
                "activeSessionId": self._active_session_id,
                "lastCompletedSessionId": self._last_completed_session_id,
            }

    def get_session_result(self, session_id: str, *, audio_state: Optional[str] = None) -> Dict[str, Any]:
        now = time.time()
        with self._lock:
            self._evict_stale_locked(now)
            record = self._session_results.get(session_id)
            active_session_id = self._active_session_id

        if not record:
            return self._empty_result(session_id)

        result = {
            "success": True,
            "sessionId": session_id,
            "state": record.get("state", "not_found"),
            "processedTranscript": record.get("processedTranscript", ""),
            "historyEntryId": record.get("historyEntryId"),
            "completedAt": record.get("completedAt"),
        }
        if session_id == active_session_id and result["state"] != "complete":
            if audio_state == "dictation":
                result["state"] = "dictation"
            elif audio_state == "processing":
                result["state"] = "processing"
        return result
