import json
from pathlib import Path

from src.history.recovery_service import RecoveryOptions, run_history_recovery


class _FakeHandler:
    def __init__(self, *args, **kwargs):
        pass

    def retranscribe_audio_file(self, audio_path: str, model_id: str) -> str:
        base = Path(audio_path).stem
        return f"Recovered text for {base} via {model_id}"


def _write_history(history_file: Path, records):
    history_file.parent.mkdir(parents=True, exist_ok=True)
    with history_file.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def test_recovery_service_dry_run_selects_redacted_records(tmp_path):
    history_file = tmp_path / "data" / "history" / "history.jsonl"
    records = [
        {
            "id": "a1",
            "transcript": "Text with [REDACTED_NAME]",
            "processedTranscript": "Text with [REDACTED_NAME]",
            "metadata": {"model": "google/medasr"},
        },
        {
            "id": "a2",
            "transcript": "Already clean text",
            "processedTranscript": "Already clean text",
            "metadata": {"model": "google/medasr"},
        },
    ]
    _write_history(history_file, records)

    result = run_history_recovery(
        RecoveryOptions(
            history_file=history_file,
            audio_dir=tmp_path / "data" / "history" / "audio",
            default_model_id="google/medasr",
            entry_ids=set(),
            limit=None,
            include_non_redacted=False,
            write=False,
        )
    )

    assert result.records_total == 2
    assert result.records_redacted == 1
    assert result.records_selected == 1
    assert result.selected_entry_ids == ["a1"]
    assert result.backup_path is None


def test_recovery_service_resumes_from_checkpoint(monkeypatch, tmp_path):
    history_file = tmp_path / "data" / "history" / "history.jsonl"
    audio_dir = tmp_path / "data" / "history" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    entry_1 = {
        "id": "entry1",
        "transcript": "Recovered text for entry1 via google/medasr",
        "processedTranscript": "Recovered text for entry1 via google/medasr",
        "metadata": {"model": "google/medasr"},
    }
    entry_2 = {
        "id": "entry2",
        "transcript": "Needs [REDACTED_NAME] recovery",
        "processedTranscript": "Needs [REDACTED_NAME] recovery",
        "metadata": {"model": "google/medasr"},
    }
    _write_history(history_file, [entry_1, entry_2])
    (audio_dir / "entry1.wav").write_bytes(b"fake")
    (audio_dir / "entry2.wav").write_bytes(b"fake")

    checkpoint = tmp_path / "recover.checkpoint.json"
    checkpoint.write_text(
        json.dumps(
            {
                "completed_entry_ids": ["entry1"],
                "processed": 1,
                "recovered": 1,
                "missing_audio": 0,
                "failed": 0,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("src.history.recovery_service.TranscriptionHandler", _FakeHandler)

    result = run_history_recovery(
        RecoveryOptions(
            history_file=history_file,
            audio_dir=audio_dir,
            default_model_id="google/medasr",
            entry_ids=set(),
            limit=None,
            include_non_redacted=False,
            write=True,
            checkpoint_file=checkpoint,
            resume=True,
            checkpoint_every=1,
        )
    )

    assert result.records_selected == 1
    assert result.skipped_from_checkpoint == 1
    assert result.processed == 2
    assert result.recovered == 2
    assert result.failed == 0
    assert result.backup_path is not None
    assert not checkpoint.exists()

    final_lines = [
        json.loads(line)
        for line in history_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    final_entry_2 = next(item for item in final_lines if item["id"] == "entry2")
    assert "[REDACTED" not in final_entry_2["transcript"]
    assert "[REDACTED" not in final_entry_2["processedTranscript"]

