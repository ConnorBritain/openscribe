"""History recovery service for rebuilding transcripts from saved audio."""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

from src.config import config
from src.text_processor import text_processor
from src.transcription_handler import TranscriptionHandler


ProgressCallback = Callable[[Dict[str, Any]], None]


@dataclass
class RecoveryOptions:
    history_file: Path
    audio_dir: Path
    default_model_id: str
    entry_ids: set[str]
    limit: int | None
    include_non_redacted: bool
    write: bool
    force_model_id: bool = False
    checkpoint_file: Path | None = None
    resume: bool = False
    checkpoint_every: int = 10


@dataclass
class RecoveryResult:
    records_total: int
    records_redacted: int
    records_selected: int
    selected_entry_ids: List[str]
    processed: int = 0
    recovered: int = 0
    missing_audio: int = 0
    failed: int = 0
    skipped_from_checkpoint: int = 0
    backup_path: Path | None = None


def default_checkpoint_file(history_file: Path) -> Path:
    return history_file.with_suffix(".recover.checkpoint.json")


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Invalid JSONL at line {line_number}: {exc}") from exc
            if not isinstance(parsed, dict):
                raise RuntimeError(f"Invalid JSONL record at line {line_number}: expected object")
            entries.append(parsed)
    return entries


def _is_redacted_record(record: Mapping[str, Any]) -> bool:
    transcript = str(record.get("transcript", ""))
    processed = str(record.get("processedTranscript", ""))
    return "[REDACTED" in transcript or "[REDACTED" in processed


def _resolve_audio_path(record: Mapping[str, Any], history_file: Path, audio_dir: Path) -> Path:
    audio_value = record.get("audioFile")
    if isinstance(audio_value, str) and audio_value.strip():
        audio_path = Path(audio_value.strip())
        if not audio_path.is_absolute():
            repo_root = history_file.resolve().parents[2]
            audio_path = (repo_root / audio_path).resolve()
    else:
        entry_id = str(record.get("id", "")).strip()
        audio_path = (audio_dir / f"{entry_id}.wav").resolve()
    return audio_path


def _select_entries(
    entries: Iterable[Dict[str, Any]],
    *,
    only_redacted: bool,
    entry_ids: set[str],
    limit: int | None,
) -> List[Dict[str, Any]]:
    selected: List[Dict[str, Any]] = []
    for record in entries:
        entry_id = str(record.get("id", ""))
        if entry_ids and entry_id not in entry_ids:
            continue
        if only_redacted and not _is_redacted_record(record):
            continue
        selected.append(record)
        if limit is not None and len(selected) >= limit:
            break
    return selected


def _write_jsonl(path: Path, entries: Iterable[Dict[str, Any]]) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
        prefix=f".{path.name}.",
        suffix=".recover.tmp",
    ) as handle:
        temp_path = Path(handle.name)
        for record in entries:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    temp_path.replace(path)


def _load_checkpoint(checkpoint_file: Path) -> Dict[str, Any]:
    if not checkpoint_file.exists():
        return {}
    try:
        with checkpoint_file.open("r", encoding="utf-8") as handle:
            parsed = json.load(handle)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return {}


def _save_checkpoint(checkpoint_file: Path, state: Dict[str, Any]) -> None:
    checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(checkpoint_file.parent),
        delete=False,
        prefix=f".{checkpoint_file.name}.",
        suffix=".tmp",
    ) as handle:
        temp_path = Path(handle.name)
        json.dump(state, handle, ensure_ascii=False, indent=2)
    temp_path.replace(checkpoint_file)


def _emit(callback: ProgressCallback | None, **payload: Any) -> None:
    if callback is None:
        return
    callback(payload)


def run_history_recovery(
    options: RecoveryOptions,
    *,
    on_progress: ProgressCallback | None = None,
) -> RecoveryResult:
    history_file = options.history_file.resolve()
    audio_dir = options.audio_dir.resolve()

    if not history_file.exists():
        raise FileNotFoundError(f"History file not found: {history_file}")

    entries = _load_jsonl(history_file)
    selected = _select_entries(
        entries,
        only_redacted=not options.include_non_redacted,
        entry_ids=options.entry_ids,
        limit=options.limit,
    )
    total_redacted = sum(1 for record in entries if _is_redacted_record(record))
    result = RecoveryResult(
        records_total=len(entries),
        records_redacted=total_redacted,
        records_selected=len(selected),
        selected_entry_ids=[str(record.get("id", "")) for record in selected],
    )

    if not options.write or not selected:
        return result

    checkpoint_file = options.checkpoint_file
    checkpoint_state: Dict[str, Any] = {}
    completed_ids: set[str] = set()
    if checkpoint_file and options.resume:
        checkpoint_state = _load_checkpoint(checkpoint_file)
        ids = checkpoint_state.get("completed_entry_ids", [])
        if isinstance(ids, list):
            completed_ids = {str(item) for item in ids if item}
            result.skipped_from_checkpoint = len(completed_ids)
        result.processed = int(checkpoint_state.get("processed", 0) or 0)
        result.recovered = int(checkpoint_state.get("recovered", 0) or 0)
        result.missing_audio = int(checkpoint_state.get("missing_audio", 0) or 0)
        result.failed = int(checkpoint_state.get("failed", 0) or 0)
    elif checkpoint_file and checkpoint_file.exists():
        try:
            checkpoint_file.unlink()
        except Exception:
            pass

    setattr(config, "MINIMAL_TERMINAL_OUTPUT", True)
    handler = TranscriptionHandler(
        on_transcription_complete_callback=None,
        on_status_update_callback=None,
        selected_asr_model=options.default_model_id,
    )

    selected_total = len(selected)
    for index, record in enumerate(selected, start=1):
        entry_id = str(record.get("id", "")).strip()
        if entry_id in completed_ids:
            continue

        result.processed += 1
        audio_path = _resolve_audio_path(record, history_file, audio_dir)
        if not audio_path.exists():
            result.missing_audio += 1
            _emit(on_progress, type="missing_audio", entry_id=entry_id, audio_path=str(audio_path))
            completed_ids.add(entry_id)
            continue

        current_model = options.default_model_id
        metadata = record.get("metadata")
        if isinstance(metadata, dict) and not options.force_model_id:
            saved_model = metadata.get("model")
            if isinstance(saved_model, str) and saved_model.strip():
                current_model = saved_model.strip()

        try:
            retranscribed = handler.retranscribe_audio_file(str(audio_path), current_model).strip()
        except Exception as exc:
            result.failed += 1
            _emit(on_progress, type="retranscribe_failed", entry_id=entry_id, error=str(exc))
            completed_ids.add(entry_id)
            continue

        if not retranscribed:
            result.failed += 1
            _emit(on_progress, type="retranscribe_empty", entry_id=entry_id)
            completed_ids.add(entry_id)
            continue

        cleaned = text_processor.clean_text(retranscribed)
        if (
            record.get("transcript") != retranscribed
            or record.get("processedTranscript") != cleaned
        ):
            record["transcript"] = retranscribed
            record["processedTranscript"] = cleaned
            result.recovered += 1

        completed_ids.add(entry_id)
        if result.processed % 10 == 0:
            _emit(
                on_progress,
                type="progress",
                processed=result.processed,
                total=selected_total,
                selection_index=index,
            )

        if checkpoint_file and result.processed % max(1, int(options.checkpoint_every)) == 0:
            _save_checkpoint(
                checkpoint_file,
                {
                    "updated_at": time.time(),
                    "history_file": str(history_file),
                    "completed_entry_ids": sorted(completed_ids),
                    "processed": result.processed,
                    "recovered": result.recovered,
                    "missing_audio": result.missing_audio,
                    "failed": result.failed,
                },
            )

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_path = history_file.with_suffix(history_file.suffix + f".pre_recover_{timestamp}.bak")
    shutil.copy2(history_file, backup_path)
    _write_jsonl(history_file, entries)
    result.backup_path = backup_path

    if checkpoint_file:
        try:
            checkpoint_file.unlink()
        except Exception:
            pass

    return result
