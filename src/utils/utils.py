import json
import os
import time
from typing import Any, Mapping

from src.config import config
from src.privacy.policies import RedactionPolicy
from src.privacy.runtime import sanitize_structured_payload, sanitize_text


def _write_log_entry(safe_label: str, log_entry: str) -> None:
    """Write a fully formatted log entry to terminal/file sinks."""
    # Controlled terminal printing: keep stdout quiet unless label is whitelisted or minimal mode is off
    try:
        if not getattr(config, "MINIMAL_TERMINAL_OUTPUT", False) or (
            hasattr(config, "TERMINAL_LOG_WHITELIST")
            and safe_label in config.TERMINAL_LOG_WHITELIST
        ):
            print(log_entry.strip())
    except Exception:
        # Fall back to printing on any config access error
        print(log_entry.strip())

    try:
        # Check if log file exists and rotate if it's too large
        if (
            os.path.exists(config.LOG_FILE)
            and os.path.getsize(config.LOG_FILE) > 1024 * 1024
        ):  # 1MB
            # Simple rotation: rename existing file with a number suffix
            os.replace(config.LOG_FILE, config.LOG_FILE + ".old")

        with open(config.LOG_FILE, "a", encoding="utf-8") as log_file:
            log_file.write(log_entry)
    except Exception as e:
        print(f"Error writing to log file {config.LOG_FILE}: {e}")


def log_event(
    label: str,
    message: str = "",
    *,
    policy: RedactionPolicy = RedactionPolicy.LOG_RUNTIME,
    fields: Mapping[str, Any] | None = None,
    **extra_fields: Any,
) -> None:
    """Structured logger with key-based PHI handling for field payloads."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    safe_label = sanitize_text(str(label), policy=policy)
    safe_message = sanitize_text(str(message or ""), policy=policy)

    merged_fields: dict[str, Any] = {}
    if isinstance(fields, Mapping):
        merged_fields.update(fields)
    merged_fields.update(extra_fields)
    merged_fields.pop("color", None)

    payload_suffix = ""
    if merged_fields:
        safe_payload = sanitize_structured_payload(merged_fields, policy=policy)
        payload_suffix = " | " + json.dumps(safe_payload, ensure_ascii=False, sort_keys=True)

    log_entry = f"{timestamp} [{safe_label}] {safe_message}{payload_suffix}\n"
    _write_log_entry(safe_label, log_entry)


def log_text(label: str, content: Any, **kwargs: Any) -> None:
    """Legacy text logger wrapper; prefers structured fields when provided."""
    policy = kwargs.pop("policy", RedactionPolicy.LOG_RUNTIME)
    if isinstance(content, Mapping):
        log_event(str(label), "", policy=policy, fields=content, **kwargs)
        return
    log_event(str(label), str(content), policy=policy, **kwargs)
