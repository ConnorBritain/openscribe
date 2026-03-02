"""Transactional text insertion helpers for clipboard paste flow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class InsertResult:
    success: bool
    inserted_text: str
    used_fallback: bool
    reason: str


class SafeTextInserter:
    """Ensures insertion never runs with empty replacement text."""

    def __init__(
        self,
        *,
        paste_callback: Callable[[str], None],
        status_callback: Optional[Callable[[str, str], None]] = None,
        log_callback: Optional[Callable[[str, str], None]] = None,
    ):
        self._paste_callback = paste_callback
        self._status_callback = status_callback
        self._log_callback = log_callback

    def _emit_status(self, message: str, color: str) -> None:
        if self._status_callback:
            try:
                self._status_callback(message, color)
            except Exception:
                pass

    def _log(self, label: str, message: str) -> None:
        if self._log_callback:
            try:
                self._log_callback(label, message)
            except Exception:
                pass

    @staticmethod
    def _normalize_text(value: Optional[str]) -> str:
        if not isinstance(value, str):
            return ""
        return value.strip()

    def notify_pending(self, message: str) -> None:
        self._emit_status(message, "orange")

    def transactional_insert(
        self,
        *,
        primary_text: Optional[str],
        fallback_text: Optional[str] = None,
        source: str = "transcription",
        append_trailing_space: bool = True,
        on_no_text_message: Optional[str] = None,
    ) -> InsertResult:
        """Insert primary text, fallback text, or no-op safely without erasing content."""
        primary = self._normalize_text(primary_text)
        fallback = self._normalize_text(fallback_text)

        candidate = ""
        used_fallback = False
        reason = "primary"

        if primary:
            candidate = primary
        elif fallback:
            candidate = fallback
            used_fallback = True
            reason = "fallback"
        else:
            reason = "empty"

        if not candidate:
            msg = on_no_text_message or f"{source.capitalize()} is not ready yet; existing text was left unchanged."
            self._emit_status(msg, "orange")
            self._log("TEXT_INSERT_SKIP", msg)
            return InsertResult(
                success=False,
                inserted_text="",
                used_fallback=False,
                reason=reason,
            )

        payload = candidate
        if append_trailing_space and not payload.endswith(" "):
            payload += " "

        try:
            self._paste_callback(payload)
        except Exception as error:
            msg = f"Failed to insert {source}: {error}"
            self._emit_status(msg, "red")
            self._log("TEXT_INSERT_ERROR", msg)
            return InsertResult(
                success=False,
                inserted_text="",
                used_fallback=used_fallback,
                reason="exception",
            )

        if used_fallback:
            restore_msg = f"{source.capitalize()} not ready. Restored previous text."
            self._emit_status(restore_msg, "orange")
            self._log("TEXT_INSERT_RESTORE", restore_msg)
        else:
            self._log("TEXT_INSERT_OK", f"Inserted {source} text ({len(candidate)} chars).")

        return InsertResult(
            success=True,
            inserted_text=candidate,
            used_fallback=used_fallback,
            reason=reason,
        )

