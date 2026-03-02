"""Runtime redaction helpers for log-time sanitization."""

from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Tuple

from src.privacy.policies import PHI_KEYS, RedactionPolicy, SENSITIVE_TEXT_FIELD_KEYS

PHI_KEYS_LOWER = {item.lower() for item in PHI_KEYS}


def _escape_regexp(value: str) -> str:
    return re.escape(value)


def _coerce_policy(options: Mapping[str, Any] | None, policy: RedactionPolicy | str | None) -> RedactionPolicy:
    if isinstance(policy, RedactionPolicy):
        return policy
    if isinstance(policy, str):
        try:
            return RedactionPolicy(policy)
        except ValueError:
            return RedactionPolicy.LOG_RUNTIME
    if isinstance(options, Mapping):
        raw = options.get("policy")
        if isinstance(raw, RedactionPolicy):
            return raw
        if isinstance(raw, str):
            try:
                return RedactionPolicy(raw)
            except ValueError:
                return RedactionPolicy.LOG_RUNTIME
    return RedactionPolicy.LOG_RUNTIME


def _normalize_options(
    options: Mapping[str, Any] | None,
    *,
    policy: RedactionPolicy | str | None = None,
) -> Tuple[list[str], list[str], bool, RedactionPolicy]:
    names: list[str] = []
    mrns: list[str] = []
    auto_detect_names = False
    resolved_policy = _coerce_policy(options, policy)
    if isinstance(options, Mapping):
        raw_names = options.get("names")
        raw_mrns = options.get("mrns")
        auto_detect_names = bool(options.get("auto_detect_names", False))
        if isinstance(raw_names, list):
            names = [str(item) for item in raw_names if item]
        if isinstance(raw_mrns, list):
            mrns = [str(item) for item in raw_mrns if item]
    return names, mrns, auto_detect_names, resolved_policy


def _extract_candidate_names(text: str) -> list[str]:
    candidates: list[str] = []
    for match in re.finditer(r"\b([A-Z][a-z]{2,}\s+[A-Z][a-z]{2,})\b", text):
        candidates.append(match.group(1))
    for match in re.finditer(r"\b([A-Z][a-z]{2,})'s\b", text):
        candidates.append(match.group(1))
    for match in re.finditer(r"(?:^|[.!?]\s+)([A-Z][a-z]{2,}),", text):
        candidates.append(match.group(1))
    for match in re.finditer(
        r"\b(?:name|named|saw|with|for|to|from|about|regarding|called|patient|pt)\s+([A-Z][a-z]{2,})\b",
        text,
        flags=re.IGNORECASE,
    ):
        candidates.append(match.group(1))
    seen: set[str] = set()
    deduped: list[str] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)
    return deduped


def _redact_names(text: str, names: list[str]) -> str:
    out = text
    patterns: list[str] = []
    for name in names:
        trimmed = (name or "").strip()
        if not trimmed:
            continue
        patterns.append(trimmed)
        for token in trimmed.split():
            if len(token) >= 3:
                patterns.append(token)
    for pattern in patterns:
        regex = re.compile(rf"\b{_escape_regexp(pattern)}\b", flags=re.IGNORECASE)
        out = regex.sub("[REDACTED_NAME]", out)
    return out


def _redact_mrns(text: str, mrns: list[str]) -> str:
    out = text
    out = re.sub(r"\bMRN\s*[:=]?\s*[A-Za-z0-9-]+\b", "MRN [REDACTED]", out, flags=re.IGNORECASE)
    out = re.sub(r"\bMRN\b\s*#?\s*[A-Za-z0-9-]+\b", "MRN [REDACTED]", out, flags=re.IGNORECASE)
    for mrn in mrns:
        trimmed = (mrn or "").strip()
        if not trimmed:
            continue
        regex = re.compile(rf"\b{_escape_regexp(trimmed)}\b", flags=re.IGNORECASE)
        out = regex.sub("[REDACTED_MRN]", out)
    return out


def _redact_labeled_names(text: str) -> str:
    out = text
    out = re.sub(r"\bPatient name\s*:\s*[^\n]+", "Patient name: [REDACTED_NAME]", out, flags=re.IGNORECASE)
    out = re.sub(r"\bPatient\s*:\s*[^\n]+", "Patient: [REDACTED_NAME]", out, flags=re.IGNORECASE)
    out = re.sub(r"\bName\s*:\s*[^\n]+", "Name: [REDACTED_NAME]", out, flags=re.IGNORECASE)
    return out


def sanitize_text(
    input_text: str,
    options: Mapping[str, Any] | None = None,
    *,
    policy: RedactionPolicy | str | None = None,
) -> str:
    """Sanitize free text according to runtime/migration policy."""
    if not isinstance(input_text, str):
        return input_text
    names, mrns, auto_detect_names, resolved_policy = _normalize_options(options, policy=policy)
    if resolved_policy == RedactionPolicy.HISTORY_NONE:
        return input_text
    if auto_detect_names:
        names = names + _extract_candidate_names(input_text)
    out = input_text
    out = _redact_mrns(out, mrns)
    out = _redact_labeled_names(out)
    out = re.sub(
        r"\b(Hi|Hello|Dear)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?",
        r"\1 [REDACTED_NAME]",
        out,
    )
    out = re.sub(
        r"\b(Mr|Ms|Mrs|Dr)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?",
        r"\1 [REDACTED_NAME]",
        out,
    )
    if names:
        out = _redact_names(out, names)
    return out


def sanitize_value(
    value: Any,
    options: Mapping[str, Any] | None = None,
    *,
    policy: RedactionPolicy | str | None = None,
) -> Any:
    """Recursively sanitize JSON-like value trees."""
    resolved_policy = _coerce_policy(options, policy)
    if resolved_policy == RedactionPolicy.HISTORY_NONE:
        return value
    if isinstance(value, str):
        return sanitize_text(value, options, policy=resolved_policy)
    if isinstance(value, list):
        return [sanitize_value(item, options, policy=resolved_policy) for item in value]
    if isinstance(value, tuple):
        return [sanitize_value(item, options, policy=resolved_policy) for item in value]
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, inner in value.items():
            if key in PHI_KEYS:
                out[key] = None
                continue
            out[key] = sanitize_value(inner, options, policy=resolved_policy)
        return out
    return value


def sanitize_structured_payload(
    payload: Mapping[str, Any],
    *,
    policy: RedactionPolicy = RedactionPolicy.LOG_RUNTIME,
) -> Dict[str, Any]:
    """Sanitize structured logging payload with key-based PHI handling."""
    if policy == RedactionPolicy.HISTORY_NONE:
        return dict(payload)
    out: Dict[str, Any] = {}
    for key, value in payload.items():
        key_lower = str(key).lower()
        if key in PHI_KEYS or key_lower in PHI_KEYS_LOWER:
            out[key] = None
            continue
        if key_lower in SENSITIVE_TEXT_FIELD_KEYS:
            out[key] = "[REDACTED_TEXT]"
            continue
        if isinstance(value, Mapping):
            out[key] = sanitize_structured_payload(value, policy=policy)
            continue
        if isinstance(value, list):
            out[key] = [
                sanitize_structured_payload(item, policy=policy) if isinstance(item, Mapping) else item
                for item in value
            ]
            continue
        out[key] = value
    return out
