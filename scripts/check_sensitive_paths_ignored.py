#!/usr/bin/env python3
"""Fail if sensitive runtime data paths are no longer git-ignored."""

from __future__ import annotations

import subprocess
import sys


SENSITIVE_PATHS = [
    "data/history/history.jsonl",
    "data/history/audio/example.wav",
    "transcript_log.txt",
    "transcript_log.txt.old",
    "main_output.log",
    "gpt_oss_debug.log",
    "clinic_data/logs/log.jsonl",
    "src/memory_logs.jsonl",
]


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=False)


def _is_tracked(path: str) -> bool:
    result = _run(["git", "ls-files", "--error-unmatch", path])
    return result.returncode == 0


def _is_ignored(path: str) -> bool:
    result = _run(["git", "check-ignore", "--no-index", path])
    return result.returncode == 0


def main() -> int:
    failures: list[str] = []
    for path in SENSITIVE_PATHS:
        tracked = _is_tracked(path)
        ignored = _is_ignored(path)
        status = []
        status.append("tracked" if tracked else "untracked")
        status.append("ignored" if ignored else "not_ignored")
        print(f"{path}: {', '.join(status)}")
        if tracked:
            failures.append(f"{path} is tracked and could be pushed.")
        elif not ignored:
            failures.append(f"{path} is not ignored.")

    if failures:
        print("\nSensitive path ignore check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("\nSensitive path ignore check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

