"""Compatibility facade for privacy redaction APIs.

This module intentionally re-exports from the split runtime and migration
modules so existing imports keep working while responsibilities stay separated.
"""

from __future__ import annotations

from src.privacy.log_migration import format_redaction_summary, redact_historical_logs
from src.privacy.policies import RedactionPolicy
from src.privacy.runtime import sanitize_structured_payload, sanitize_text, sanitize_value

__all__ = [
    "RedactionPolicy",
    "sanitize_text",
    "sanitize_value",
    "sanitize_structured_payload",
    "redact_historical_logs",
    "format_redaction_summary",
]

