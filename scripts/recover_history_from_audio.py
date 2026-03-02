#!/usr/bin/env python3
"""Recover history transcripts by retranscribing saved audio."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.config import config
from src.config.settings_manager import settings_manager
from src.history.recovery_service import (
    RecoveryOptions,
    default_checkpoint_file,
    run_history_recovery,
)


def _default_model_id() -> str:
    return settings_manager.get_setting("selectedAsrModel", config.DEFAULT_ASR_MODEL)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history-file", default="data/history/history.jsonl", help="Path to history JSONL file")
    parser.add_argument("--audio-dir", default="data/history/audio", help="Directory containing per-entry WAV files")
    parser.add_argument("--model-id", default=None, help="ASR model id to use (default: per-entry metadata/default)")
    parser.add_argument("--entry-id", action="append", default=[], help="Specific entry id(s) to recover")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of matching entries to process")
    parser.add_argument(
        "--include-non-redacted",
        action="store_true",
        help="Process entries even if they do not contain [REDACTED...]",
    )
    parser.add_argument("--write", action="store_true", help="Write recovered transcripts (default: dry-run)")
    parser.add_argument(
        "--checkpoint-file",
        default=None,
        help="Checkpoint file path (default: alongside history file)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from existing checkpoint file when present",
    )
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=10,
        help="Persist checkpoint every N processed entries",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    history_file = Path(args.history_file).resolve()
    audio_dir = Path(args.audio_dir).resolve()
    selected_model = args.model_id or _default_model_id()
    checkpoint_file = (
        Path(args.checkpoint_file).resolve()
        if args.checkpoint_file
        else default_checkpoint_file(history_file).resolve()
    )
    entry_ids = {str(item).strip() for item in args.entry_id if str(item).strip()}

    options = RecoveryOptions(
        history_file=history_file,
        audio_dir=audio_dir,
        default_model_id=selected_model,
        entry_ids=entry_ids,
        limit=args.limit,
        include_non_redacted=bool(args.include_non_redacted),
        write=bool(args.write),
        force_model_id=bool(args.model_id),
        checkpoint_file=checkpoint_file if args.write else None,
        resume=bool(args.resume),
        checkpoint_every=max(1, int(args.checkpoint_every or 10)),
    )

    def _emit(payload):
        payload_type = payload.get("type")
        if payload_type == "progress":
            print(f"progress={payload.get('processed')}/{payload.get('total')}")
            return
        if payload_type == "missing_audio":
            print(f"missing_audio={payload.get('entry_id')}:{payload.get('audio_path')}")
            return
        if payload_type == "retranscribe_failed":
            print(f"retranscribe_failed={payload.get('entry_id')}:{payload.get('error')}")
            return
        if payload_type == "retranscribe_empty":
            print(f"retranscribe_empty={payload.get('entry_id')}")

    try:
        result = run_history_recovery(options, on_progress=_emit)
    except FileNotFoundError as exc:
        print(str(exc))
        return 1

    print(f"history_file={history_file}")
    print(f"audio_dir={audio_dir}")
    print(f"selected_model={selected_model}")
    print(f"records_total={result.records_total}")
    print(f"records_redacted={result.records_redacted}")
    print(f"records_selected={result.records_selected}")

    if not args.write:
        for entry_id in result.selected_entry_ids[:25]:
            print(f"dry_run_entry={entry_id}")
        if len(result.selected_entry_ids) > 25:
            print(f"dry_run_omitted={len(result.selected_entry_ids) - 25}")
        print("dry_run=true (use --write to apply changes)")
        return 0

    if result.skipped_from_checkpoint:
        print(f"resumed_skipped={result.skipped_from_checkpoint}")
    print(f"processed={result.processed}")
    print(f"recovered={result.recovered}")
    print(f"missing_audio={result.missing_audio}")
    print(f"failed={result.failed}")
    if result.backup_path is not None:
        print(f"backup={result.backup_path}")
    return 0 if result.failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
