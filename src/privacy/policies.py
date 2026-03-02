"""Typed policy definitions for privacy redaction behavior."""

from __future__ import annotations

from enum import Enum


class RedactionPolicy(str, Enum):
    """Policy profiles for where/how redaction should apply."""

    LOG_RUNTIME = "log_runtime"
    LOG_MIGRATION = "log_migration"
    HISTORY_NONE = "history_none"


PHI_KEYS = frozenset({"mrn", "patient_name", "patientName"})

# Structured log fields that should not carry full free-text transcripts.
SENSITIVE_TEXT_FIELD_KEYS = frozenset(
    {
        "transcript",
        "raw_transcript",
        "processedtranscript",
        "rawtranscript",
        "raw_text",
        "original_text",
        "processed_text",
        "before_text",
        "after_text",
        "dictation_text",
        "full_text",
    }
)
