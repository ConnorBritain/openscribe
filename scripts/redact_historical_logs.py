#!/usr/bin/env python3
"""Redact historical logs in OpenScribe."""

from __future__ import annotations

from pathlib import Path

from src.privacy.log_migration import format_redaction_summary, redact_historical_logs


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    summary = redact_historical_logs(repo_root)
    print(format_redaction_summary(summary))
    return 0 if summary.get("errors", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
