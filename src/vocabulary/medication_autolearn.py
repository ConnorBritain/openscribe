"""Hands-off medication auto-learn service with guarded auto-apply rules."""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from .medication_error_analyzer import analyze_history_incremental
from .vocabulary_manager import VocabularyManager, get_vocabulary_manager


SummaryPayload = Dict[str, Any]


@dataclass
class MedicationAutoLearnSummary:
    lastRunAt: Optional[str]
    scannedRecords: int
    importedMappings: int
    queuedReviews: int
    pendingReviews: int
    lastProcessedHistoryLine: int
    runReason: str
    durationMs: int
    error: Optional[str] = None

    def to_dict(self) -> SummaryPayload:
        return {
            "lastRunAt": self.lastRunAt,
            "scannedRecords": int(self.scannedRecords),
            "importedMappings": int(self.importedMappings),
            "queuedReviews": int(self.queuedReviews),
            "pendingReviews": int(self.pendingReviews),
            "lastProcessedHistoryLine": int(self.lastProcessedHistoryLine),
            "runReason": str(self.runReason),
            "durationMs": int(self.durationMs),
            "error": self.error,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Optional[Dict[str, Any]],
        *,
        default_reason: str = "none",
        default_last_run_at: Optional[str] = None,
    ) -> "MedicationAutoLearnSummary":
        source = payload or {}
        return cls(
            lastRunAt=source.get("lastRunAt", default_last_run_at),
            scannedRecords=int(source.get("scannedRecords", 0) or 0),
            importedMappings=int(source.get("importedMappings", 0) or 0),
            queuedReviews=int(source.get("queuedReviews", 0) or 0),
            pendingReviews=int(source.get("pendingReviews", 0) or 0),
            lastProcessedHistoryLine=int(source.get("lastProcessedHistoryLine", 0) or 0),
            runReason=str(source.get("runReason", default_reason)),
            durationMs=int(source.get("durationMs", 0) or 0),
            error=source.get("error"),
        )


class MedicationAutoLearnService:
    """Background service for incremental medication mapping auto-learning."""

    MIN_NEW_DICTATIONS = 5
    MIN_IDLE_SECONDS = 90
    COOLDOWN_SECONDS = 15 * 60
    MIN_RETRY_SECONDS = 5

    def __init__(
        self,
        *,
        vocab_manager: Optional[VocabularyManager] = None,
        settings_enabled_getter: Optional[Callable[[], bool]] = None,
        busy_check: Optional[Callable[[], bool]] = None,
        on_run_complete: Optional[Callable[[SummaryPayload], None]] = None,
        state_path: str = "data/medication_autolearn_state.json",
        history_path: str = "data/history/history.jsonl",
        lexicon_path: str = "data/medical_lexicon.json",
        user_vocabulary_path: Optional[str] = None,
        time_fn: Optional[Callable[[], float]] = None,
        monotonic_fn: Optional[Callable[[], float]] = None,
    ):
        self.vocab_manager = vocab_manager or get_vocabulary_manager()
        self._settings_enabled_getter = settings_enabled_getter or (lambda: True)
        self._busy_check = busy_check or (lambda: False)
        self._on_run_complete = on_run_complete
        self._wall_time_fn = time_fn or time.time
        self._monotonic_fn = monotonic_fn or time_fn or time.monotonic

        self.state_path = Path(state_path)
        self.history_path = Path(history_path)
        self.lexicon_path = Path(lexicon_path)
        self.user_vocabulary_path = (
            Path(user_vocabulary_path)
            if user_vocabulary_path
            else Path(self.vocab_manager.vocabulary_file)
        )

        self._run_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._schedule_lock = threading.Lock()
        self._scheduled_timer: Optional[threading.Timer] = None
        self._runtime_enabled: Optional[bool] = None
        self._env_disabled = os.getenv("CT_MEDICATION_AUTOLEARN_DISABLED", "0") == "1"

        self.state = self._load_state()
        self._last_run_monotonic: Optional[float] = None
        self._sync_last_run_monotonic_from_state()
        self._last_activity_at = self._monotonic_now()

    def _wall_now(self) -> float:
        return float(self._wall_time_fn())

    def _monotonic_now(self) -> float:
        return float(self._monotonic_fn())

    def _utc_now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _default_state(self) -> Dict[str, Any]:
        return {
            "newDictationCount": 0,
            "lastRunAt": None,
            "lastProcessedHistoryLine": 0,
            "lastSummary": None,
        }

    def _load_state(self) -> Dict[str, Any]:
        default_state = self._default_state()
        if not self.state_path.exists():
            self._write_state(default_state)
            return dict(default_state)
        try:
            with self.state_path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}

        merged = dict(default_state)
        merged.update(payload)
        merged["newDictationCount"] = int(merged.get("newDictationCount", 0) or 0)
        merged["lastProcessedHistoryLine"] = int(merged.get("lastProcessedHistoryLine", 0) or 0)
        if merged["newDictationCount"] < 0:
            merged["newDictationCount"] = 0
        if merged["lastProcessedHistoryLine"] < 0:
            merged["lastProcessedHistoryLine"] = 0
        self._write_state(merged)
        return merged

    def _write_state(self, payload: Dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(payload, indent=2, ensure_ascii=False)
        tmp_path = self.state_path.with_suffix(
            f"{self.state_path.suffix}.tmp.{os.getpid()}.{threading.get_ident()}"
        )
        try:
            with tmp_path.open("w", encoding="utf-8") as f:
                f.write(serialized)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.state_path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def _save_state(self) -> None:
        with self._state_lock:
            self._write_state(dict(self.state))

    def _pending_review_count(self) -> int:
        try:
            queue = self.vocab_manager.get_medication_review_queue(status_filter="pending")
            return len(queue)
        except Exception:
            return 0

    def _parse_last_run_epoch(self) -> Optional[float]:
        last_run_at = self.state.get("lastRunAt")
        if not last_run_at:
            return None
        try:
            return datetime.fromisoformat(str(last_run_at)).timestamp()
        except Exception:
            return None

    def _sync_last_run_monotonic_from_state(self) -> None:
        last_run_epoch = self._parse_last_run_epoch()
        if last_run_epoch is None:
            self._last_run_monotonic = None
            return
        elapsed = max(0.0, self._wall_now() - last_run_epoch)
        self._last_run_monotonic = self._monotonic_now() - elapsed

    def _is_auto_enabled(self) -> bool:
        if self._env_disabled:
            return False
        if self._runtime_enabled is not None:
            return bool(self._runtime_enabled)
        try:
            return bool(self._settings_enabled_getter())
        except Exception:
            return True

    def set_runtime_enabled(self, enabled: bool) -> None:
        self._runtime_enabled = bool(enabled)
        if not self._runtime_enabled:
            self._cancel_timer()
        else:
            self.schedule_background_check()

    def notify_dictation_completed(self) -> None:
        """Increment dictation counter and schedule background eligibility check."""
        self.state["newDictationCount"] = int(self.state.get("newDictationCount", 0) or 0) + 1
        self._last_activity_at = self._monotonic_now()
        self._save_state()
        self.schedule_background_check()

    def notify_activity(self) -> None:
        """Mark a user activity point for idle-gate timing."""
        self._last_activity_at = self._monotonic_now()

    def _cancel_timer(self) -> None:
        with self._schedule_lock:
            timer = self._scheduled_timer
            self._scheduled_timer = None
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                pass

    def _schedule_after(self, delay_seconds: float) -> None:
        delay = max(self.MIN_RETRY_SECONDS, float(delay_seconds))

        def _run_tick() -> None:
            with self._schedule_lock:
                self._scheduled_timer = None
            self.run_if_due()

        with self._schedule_lock:
            existing = self._scheduled_timer
            if existing is not None:
                try:
                    existing.cancel()
                except Exception:
                    pass
            timer = threading.Timer(delay, _run_tick)
            timer.daemon = True
            self._scheduled_timer = timer
            timer.start()

    def _remaining_cooldown_seconds(self) -> float:
        if self._last_run_monotonic is None:
            self._sync_last_run_monotonic_from_state()
        if self._last_run_monotonic is None:
            return 0.0
        return max(0.0, (self._last_run_monotonic + self.COOLDOWN_SECONDS) - self._monotonic_now())

    def _current_idle_seconds(self) -> float:
        if self._busy_check():
            return 0.0
        return max(0.0, self._monotonic_now() - self._last_activity_at)

    def _auto_gate(self) -> Tuple[bool, Optional[float], str]:
        if self._env_disabled:
            return False, None, "disabled_by_env"
        if not self._is_auto_enabled():
            return False, None, "disabled_by_setting"

        new_dictation_count = int(self.state.get("newDictationCount", 0) or 0)
        if new_dictation_count < self.MIN_NEW_DICTATIONS:
            return False, None, "waiting_for_more_dictations"

        if self._busy_check():
            return False, float(self.MIN_IDLE_SECONDS), "busy"

        idle_seconds = self._current_idle_seconds()
        if idle_seconds < self.MIN_IDLE_SECONDS:
            return False, float(self.MIN_IDLE_SECONDS - idle_seconds), "idle_gate"

        cooldown_seconds = self._remaining_cooldown_seconds()
        if cooldown_seconds > 0:
            return False, cooldown_seconds, "cooldown"

        return True, None, "ready"

    def schedule_background_check(self) -> None:
        if self._env_disabled:
            return
        eligible, next_delay, _ = self._auto_gate()
        if eligible:
            self._schedule_after(self.MIN_RETRY_SECONDS)
            return
        if next_delay is not None:
            self._schedule_after(next_delay)

    def run_if_due(self) -> SummaryPayload:
        """Run auto-learn only when policy gates are satisfied."""
        eligible, next_delay, reason = self._auto_gate()
        if not eligible:
            if next_delay is not None:
                self._schedule_after(next_delay)
            return self._status_summary_template(run_reason=f"auto:{reason}")
        return self._execute_run(run_reason="auto")

    def run_now(self) -> SummaryPayload:
        """Force a manual run (except for hard env disable)."""
        if self._env_disabled:
            return self._status_summary_template(
                run_reason="manual:disabled_by_env",
                error="Medication auto-learn is disabled by CT_MEDICATION_AUTOLEARN_DISABLED=1",
            )
        return self._execute_run(run_reason="manual")

    def _status_summary_template(self, run_reason: str, error: Optional[str] = None) -> SummaryPayload:
        summary = MedicationAutoLearnSummary(
            lastRunAt=self.state.get("lastRunAt"),
            scannedRecords=0,
            importedMappings=0,
            queuedReviews=0,
            pendingReviews=self._pending_review_count(),
            lastProcessedHistoryLine=int(self.state.get("lastProcessedHistoryLine", 0) or 0),
            runReason=run_reason,
            durationMs=0,
            error=error,
        )
        return summary.to_dict()

    def _emit_summary(self, summary: SummaryPayload) -> None:
        callback = self._on_run_complete
        if callback is None:
            return
        try:
            callback(summary)
        except Exception:
            # Non-fatal. Service should never raise because of UI/status callback failures.
            pass

    def _execute_run(self, run_reason: str) -> SummaryPayload:
        if not self._run_lock.acquire(blocking=False):
            return self._status_summary_template(
                run_reason=f"{run_reason}:already_running",
                error="Medication auto-learn run already in progress",
            )

        started = self._monotonic_now()
        now_iso = self._utc_now_iso()
        try:
            start_line = int(self.state.get("lastProcessedHistoryLine", 0) or 0)
            analysis = analyze_history_incremental(
                history_path=self.history_path,
                lexicon_path=self.lexicon_path,
                user_vocabulary_path=self.user_vocabulary_path if self.user_vocabulary_path.exists() else None,
                start_line=start_line,
            )
            candidates = analysis.get("candidates", []) or []

            imported = 0
            queued = 0

            for candidate in candidates:
                observed = str(candidate.get("observed") or "").strip()
                suggested = str(candidate.get("suggested") or "").strip()
                confidence = str(candidate.get("confidence") or "low").strip().lower()
                evidence = str(candidate.get("evidence") or "")
                sample_context = str(candidate.get("sample_context") or "")
                occurrences = max(1, int(candidate.get("occurrences", 1) or 1))
                entry_count = max(1, int(candidate.get("entry_count", 1) or 1))

                if not observed or not suggested:
                    continue

                if confidence == "high" and occurrences >= 2:
                    self.vocab_manager.add_medication_mapping(
                        observed=observed,
                        canonical=suggested,
                        source="auto_learn",
                        confidence="high",
                        occurrence_count=occurrences,
                        entry_count=entry_count,
                        save=False,
                    )
                    imported += 1
                elif confidence == "medium":
                    review = self.vocab_manager.queue_medication_review(
                        observed=observed,
                        suggested=suggested,
                        confidence="medium",
                        evidence=evidence,
                        occurrence_count=occurrences,
                        entry_count=entry_count,
                        sample_context=sample_context,
                        source="auto_learn",
                        save=False,
                    )
                    if str(review.get("status")) != "rejected":
                        queued += 1

            if imported > 0 or queued > 0:
                self.vocab_manager.save_vocabulary()

            last_processed_history_line = int(analysis.get("last_processed_history_line", start_line) or start_line)
            scanned_records = int(analysis.get("scanned_records", 0) or 0)

            self.state["newDictationCount"] = 0
            self.state["lastRunAt"] = now_iso
            self.state["lastProcessedHistoryLine"] = last_processed_history_line
            self._last_run_monotonic = self._monotonic_now()

            summary = MedicationAutoLearnSummary(
                lastRunAt=now_iso,
                scannedRecords=scanned_records,
                importedMappings=imported,
                queuedReviews=queued,
                pendingReviews=self._pending_review_count(),
                lastProcessedHistoryLine=last_processed_history_line,
                runReason=run_reason,
                durationMs=int((self._monotonic_now() - started) * 1000),
                error=None,
            ).to_dict()
            self.state["lastSummary"] = summary
            self._save_state()
            self._emit_summary(summary)
            return summary

        except Exception as error:
            summary = MedicationAutoLearnSummary(
                lastRunAt=now_iso,
                scannedRecords=0,
                importedMappings=0,
                queuedReviews=0,
                pendingReviews=self._pending_review_count(),
                lastProcessedHistoryLine=int(self.state.get("lastProcessedHistoryLine", 0) or 0),
                runReason=run_reason,
                durationMs=int((self._monotonic_now() - started) * 1000),
                error=str(error),
            ).to_dict()
            self.state["lastRunAt"] = now_iso
            self._last_run_monotonic = self._monotonic_now()
            self.state["lastSummary"] = summary
            self._save_state()
            self._emit_summary(summary)
            return summary
        finally:
            self._run_lock.release()

    def get_status(self) -> Dict[str, Any]:
        last_summary = MedicationAutoLearnSummary.from_dict(
            self.state.get("lastSummary") if isinstance(self.state.get("lastSummary"), dict) else None,
            default_reason="none",
            default_last_run_at=self.state.get("lastRunAt"),
        ).to_dict()

        return {
            "success": True,
            "enabled": self._is_auto_enabled(),
            "envDisabled": self._env_disabled,
            "newDictationCount": int(self.state.get("newDictationCount", 0) or 0),
            "lastRunAt": self.state.get("lastRunAt"),
            "lastProcessedHistoryLine": int(self.state.get("lastProcessedHistoryLine", 0) or 0),
            "pendingReviews": self._pending_review_count(),
            "isRunning": self._run_lock.locked(),
            "lastSummary": last_summary,
        }

    def shutdown(self) -> None:
        self._cancel_timer()


_global_service: Optional[MedicationAutoLearnService] = None
_global_service_lock = threading.Lock()


def set_global_medication_autolearn_service(service: Optional[MedicationAutoLearnService]) -> None:
    global _global_service
    with _global_service_lock:
        _global_service = service


def get_global_medication_autolearn_service() -> Optional[MedicationAutoLearnService]:
    with _global_service_lock:
        return _global_service
