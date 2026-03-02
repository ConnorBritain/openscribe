"""Application-level dictate lifecycle state machine."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, Set

from src import ipc_contract


@dataclass(frozen=True)
class LifecycleSnapshot:
    state: str
    previous_state: str
    reason: str
    updated_at: float


class DictationLifecycleStateMachine:
    """Tracks high-level dictation lifecycle transitions across backend + UI."""

    _ALLOWED_TRANSITIONS: Dict[str, Set[str]] = {
        "idle": {"idle", "listening", "recording", "error"},
        "listening": {"idle", "listening", "recording", "error"},
        "recording": {"idle", "recording", "stopping", "transcribing", "error"},
        "stopping": {"idle", "stopping", "transcribing", "error"},
        "transcribing": {"idle", "listening", "transcribing", "inserting", "error"},
        "inserting": {"idle", "listening", "inserting", "error"},
        "error": {"idle", "listening", "error"},
    }

    def __init__(self, initial_state: str = "idle"):
        if not ipc_contract.validate_lifecycle_state(initial_state):
            initial_state = "idle"
        self._state = initial_state
        self._previous_state = initial_state
        self._reason = "init"
        self._updated_at = time.time()
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        return self._state

    @property
    def reason(self) -> str:
        return self._reason

    def snapshot(self) -> LifecycleSnapshot:
        with self._lock:
            return LifecycleSnapshot(
                state=self._state,
                previous_state=self._previous_state,
                reason=self._reason,
                updated_at=self._updated_at,
            )

    def transition(self, next_state: str, *, reason: str = "", force: bool = False) -> bool:
        if not ipc_contract.validate_lifecycle_state(next_state):
            raise ValueError(f"Invalid lifecycle state: {next_state}")

        with self._lock:
            allowed_targets = self._ALLOWED_TRANSITIONS.get(self._state, set())
            if not force and next_state not in allowed_targets:
                raise ValueError(
                    f"Invalid lifecycle transition: {self._state} -> {next_state}"
                )

            if (
                not force
                and next_state == self._state
                and (reason or self._reason) == self._reason
            ):
                return False

            self._previous_state = self._state
            self._state = next_state
            self._reason = reason or self._reason
            self._updated_at = time.time()
            return True

    def sync_from_audio_state(
        self,
        *,
        audio_state: str,
        program_active: bool,
        wake_word_enabled: bool = True,
        microphone_error: str | None = None,
        reason: str = "",
    ) -> str:
        if microphone_error:
            self.transition("error", reason=reason or "microphone_error", force=True)
            return self._state

        if not program_active:
            self.transition("idle", reason=reason or "program_inactive", force=True)
            return self._state

        if audio_state == "dictation":
            self.transition("recording", reason=reason or "audio_dictation", force=True)
            return self._state

        if audio_state == "processing":
            current = self._state
            if current == "inserting":
                return self._state
            if current == "stopping":
                self.transition("transcribing", reason=reason or "stop_processing", force=True)
            else:
                self.transition("transcribing", reason=reason or "audio_processing", force=True)
            return self._state

        if audio_state in {"activation", "preparing"}:
            if wake_word_enabled:
                self.transition("listening", reason=reason or "audio_activation", force=True)
            else:
                self.transition("idle", reason=reason or "wake_word_disabled", force=True)
            return self._state

        self.transition("idle", reason=reason or "audio_inactive", force=True)
        return self._state

