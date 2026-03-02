"""Historical log redaction utilities (batch migration path)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Dict

from src.privacy.policies import RedactionPolicy
from src.privacy.runtime import sanitize_text, sanitize_value


LOG_SUFFIXES = {".log", ".jsonl"}
# Keep user-facing dictation history untouched; this scanner is for logs.
EXCLUDED_LOG_RELATIVE_PATHS = {
    "data/history/history.jsonl",
}
EXCLUDED_LOG_RELATIVE_PREFIXES = (
    "data/history/",
)
EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    ".venv",
    ".venv_py311",
    "venv",
    "whisper_env",
    "models",
    "vosk",
    "openwakeword",
}


def _discover_log_files(repo_root: Path) -> list[Path]:
    discovered: list[Path] = []
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [name for name in dirs if name not in EXCLUDED_DIRS]
        for file_name in files:
            file_path = Path(root) / file_name
            relative_path = file_path.relative_to(repo_root).as_posix()
            if relative_path in EXCLUDED_LOG_RELATIVE_PATHS:
                continue
            if relative_path.startswith(EXCLUDED_LOG_RELATIVE_PREFIXES):
                continue
            if file_name.startswith("transcript_log.txt"):
                discovered.append(file_path)
                continue
            if file_path.suffix.lower() in LOG_SUFFIXES:
                discovered.append(file_path)
    return sorted(set(discovered))


def _rewrite_with_transform(path: Path, transform_line) -> bool:
    changed = False
    temp_file = None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as source:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(path.parent),
                delete=False,
                prefix=f".{path.name}.",
                suffix=".redact.tmp",
            ) as target:
                temp_file = Path(target.name)
                for original in source:
                    updated = transform_line(original)
                    if updated != original:
                        changed = True
                    target.write(updated)
    except FileNotFoundError:
        return False

    if temp_file is None:
        return False

    if changed:
        os.replace(temp_file, path)
        return True

    try:
        temp_file.unlink(missing_ok=True)
    except Exception:
        pass
    return False


def _redact_text_file(path: Path) -> bool:
    def transform_line(line: str) -> str:
        suffix = "\n" if line.endswith("\n") else ""
        body = line[:-1] if suffix else line
        return sanitize_text(body, policy=RedactionPolicy.LOG_MIGRATION) + suffix

    return _rewrite_with_transform(path, transform_line)


def _redact_jsonl_file(path: Path) -> bool:
    def transform_line(line: str) -> str:
        if not line.strip():
            return line
        suffix = "\n" if line.endswith("\n") else ""
        body = line[:-1] if suffix else line
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return sanitize_text(body, policy=RedactionPolicy.LOG_MIGRATION) + suffix

        sanitized = sanitize_value(parsed, policy=RedactionPolicy.LOG_MIGRATION)
        return json.dumps(sanitized, ensure_ascii=False) + suffix

    return _rewrite_with_transform(path, transform_line)


def redact_historical_logs(repo_root: str | Path) -> Dict[str, int]:
    """Redact historical logs in-place and return summary counters."""
    root = Path(repo_root).resolve()
    processed = 0
    redacted = 0
    errors = 0
    for path in _discover_log_files(root):
        processed += 1
        try:
            if path.suffix.lower() == ".jsonl":
                changed = _redact_jsonl_file(path)
            else:
                changed = _redact_text_file(path)
            if changed:
                redacted += 1
        except Exception:
            errors += 1
    return {
        "processed_files": processed,
        "redacted_files": redacted,
        "errors": errors,
    }


def format_redaction_summary(summary: Dict[str, int]) -> str:
    return (
        f"processed={summary.get('processed_files', 0)}, "
        f"redacted={summary.get('redacted_files', 0)}, "
        f"errors={summary.get('errors', 0)}"
    )

