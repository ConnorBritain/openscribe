import json
from pathlib import Path

from src.config import config
from src.history.history_manager import HistoryManager
from src.privacy.redaction import (
    RedactionPolicy,
    redact_historical_logs,
    sanitize_structured_payload,
    sanitize_text,
    sanitize_value,
)
from src.utils.utils import log_event, log_text


def test_sanitize_text_redacts_mrn_and_names():
    input_text = "Patient: Jane Doe\nMRN 123456\nHello Jane Doe"
    output = sanitize_text(input_text, {"names": ["Jane Doe"], "mrns": ["123456"]})
    assert "Jane Doe" not in output
    assert "123456" not in output
    assert "Patient: [REDACTED_NAME]" in output
    assert "MRN [REDACTED]" in output


def test_sanitize_value_recursively_nulls_phi_keys():
    payload = {
        "mrn": "123456",
        "patient_name": "Jane Doe",
        "nested": {"patientName": "Jane Doe", "note": "Hi Jane Doe"},
    }
    redacted = sanitize_value(payload, {"names": ["Jane Doe"], "mrns": ["123456"]})
    assert redacted["mrn"] is None
    assert redacted["patient_name"] is None
    assert redacted["nested"]["patientName"] is None
    assert "Jane Doe" not in redacted["nested"]["note"]


def test_sanitize_text_history_policy_none_is_noop():
    input_text = "Patient: Jane Doe MRN 123456"
    output = sanitize_text(input_text, policy=RedactionPolicy.HISTORY_NONE)
    assert output == input_text


def test_sanitize_structured_payload_masks_sensitive_fields():
    payload = {
        "mrn": "123456",
        "transcript": "Patient: Jane Doe MRN 123456",
        "note": "safe note",
        "nested": {"patient_name": "Jane Doe"},
    }
    redacted = sanitize_structured_payload(payload)
    assert redacted["mrn"] is None
    assert redacted["transcript"] == "[REDACTED_TEXT]"
    assert redacted["note"] == "safe note"
    assert redacted["nested"]["patient_name"] is None


def test_log_text_writes_redacted_content(tmp_path, monkeypatch):
    log_file = tmp_path / "transcript_log.txt"
    monkeypatch.setattr(config, "LOG_FILE", str(log_file), raising=False)
    monkeypatch.setattr(config, "MINIMAL_TERMINAL_OUTPUT", True, raising=False)
    monkeypatch.setattr(config, "TERMINAL_LOG_WHITELIST", set(), raising=False)

    log_text("TEST", "Patient: Jane Doe MRN 123456")

    contents = log_file.read_text(encoding="utf-8")
    assert "Jane Doe" not in contents
    assert "123456" not in contents
    assert "Patient: [REDACTED_NAME]" in contents


def test_log_text_preserves_non_phi_content(tmp_path, monkeypatch):
    log_file = tmp_path / "transcript_log.txt"
    monkeypatch.setattr(config, "LOG_FILE", str(log_file), raising=False)
    monkeypatch.setattr(config, "MINIMAL_TERMINAL_OUTPUT", True, raising=False)
    monkeypatch.setattr(config, "TERMINAL_LOG_WHITELIST", set(), raising=False)

    message = "We plan to continue treatment for pain and monitor weekly."
    log_text("TRANSCRIPTION_COMPLETE", message)

    contents = log_file.read_text(encoding="utf-8")
    assert message in contents
    assert "[REDACTED_NAME]" not in contents


def test_log_event_masks_structured_transcript_fields(tmp_path, monkeypatch):
    log_file = tmp_path / "transcript_log.txt"
    monkeypatch.setattr(config, "LOG_FILE", str(log_file), raising=False)
    monkeypatch.setattr(config, "MINIMAL_TERMINAL_OUTPUT", True, raising=False)
    monkeypatch.setattr(config, "TERMINAL_LOG_WHITELIST", set(), raising=False)

    log_event(
        "TRANSCRIBED",
        "transcription_complete",
        transcript="Patient: Jane Doe",
        duration_seconds=2.1,
        mrn="123456",
    )

    contents = log_file.read_text(encoding="utf-8")
    assert "transcription_complete" in contents
    assert "[REDACTED_TEXT]" in contents
    assert '"mrn": null' in contents
    assert "Jane Doe" not in contents


def test_history_manager_writes_raw_history(tmp_path):
    base_dir = tmp_path / "history"
    manager = HistoryManager(base_dir=str(base_dir))

    record = manager.add_entry(
        entry_id="abc123",
        transcript="Patient: Jane Doe MRN 123456",
        processed_transcript="Hello Jane Doe",
        duration_seconds=1.2,
        audio_bytes=None,
        started_at=1.0,
        completed_at=2.0,
        metadata={"mrn": "123456", "patient_name": "Jane Doe", "note": "Dr Smith reviewed"},
    )

    assert "Jane Doe" in record["transcript"]
    assert "123456" in record["transcript"]
    assert record["metadata"]["mrn"] == "123456"
    assert record["metadata"]["patient_name"] == "Jane Doe"
    assert "Smith" in record["metadata"]["note"]

    history_log = Path(base_dir) / "history.jsonl"
    saved = json.loads(history_log.read_text(encoding="utf-8").strip())
    assert "Jane Doe" in saved["transcript"]
    assert "123456" in saved["transcript"]
    assert saved["metadata"]["mrn"] == "123456"


def test_redact_historical_logs_skips_history_jsonl(tmp_path):
    history_dir = tmp_path / "data" / "history"
    history_dir.mkdir(parents=True)
    history_log = history_dir / "history.jsonl"
    history_log.write_text(
        '{"transcript":"Patient: Jane Doe MRN 123456","metadata":{"mrn":"123456"}}\n',
        encoding="utf-8",
    )

    transcript_log = tmp_path / "transcript_log.txt"
    transcript_log.write_text("Patient: Jane Doe MRN 123456\n", encoding="utf-8")

    summary = redact_historical_logs(tmp_path)

    assert summary["processed_files"] == 1
    assert summary["redacted_files"] == 1
    assert "Jane Doe" in history_log.read_text(encoding="utf-8")
    assert "123456" in history_log.read_text(encoding="utf-8")
    redacted_log = transcript_log.read_text(encoding="utf-8")
    assert "Jane Doe" not in redacted_log
    assert "123456" not in redacted_log
