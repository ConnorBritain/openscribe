"""Shared IPC schema helpers for Python backend components."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

_CONTRACT_PATH = Path(__file__).resolve().parents[1] / "shared" / "ipc_contract.json"

_DEFAULT_CONTRACT = {
    "version": 1,
    "prefixes": {
        "state": "STATE:",
        "status": "STATUS:",
        "audioMetrics": "AUDIO_METRICS:",
        "audioAmplitudeLegacy": "AUDIO_AMP:",
        "audioLevelsLegacy": "AUDIO_LEVELS:",
        "finalTranscript": "FINAL_TRANSCRIPT:",
        "historyEntry": "HISTORY_ENTRY:",
        "retranscribeStart": "RETRANSCRIBE_START:",
        "retranscribeEnd": "RETRANSCRIBE_END:",
        "retranscribeQuickResult": "RETRANSCRIBE_QUICK_RESULT:",
        "hotkeys": "HOTKEYS:",
        "transcribeFileProgress": "TRANSCRIBE_FILE_PROGRESS:",
        "transcribeFileResult": "TRANSCRIBE_FILE_RESULT:",
        "audioSourceLevels": "AUDIO_SOURCE_LEVELS:",
    },
    "audioStates": ["inactive", "preparing", "activation", "dictation", "processing"],
    "lifecycleStates": [
        "idle",
        "listening",
        "recording",
        "stopping",
        "transcribing",
        "inserting",
        "error",
    ],
}


def _load_contract() -> Dict[str, Any]:
    try:
        with _CONTRACT_PATH.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
            if isinstance(payload, dict):
                return payload
    except Exception:
        pass
    return dict(_DEFAULT_CONTRACT)


CONTRACT: Dict[str, Any] = _load_contract()
IPC_SCHEMA_VERSION: int = int(CONTRACT.get("version", 1))

PREFIXES: Dict[str, str] = dict(_DEFAULT_CONTRACT.get("prefixes", {}))
PREFIXES.update(CONTRACT.get("prefixes", {}))

VALID_AUDIO_STATES = set(CONTRACT.get("audioStates", _DEFAULT_CONTRACT["audioStates"]))
VALID_LIFECYCLE_STATES = set(
    CONTRACT.get("lifecycleStates", _DEFAULT_CONTRACT["lifecycleStates"])
)

_AUDIO_TO_LIFECYCLE = {
    "inactive": "idle",
    "preparing": "idle",
    "activation": "listening",
    "dictation": "recording",
    "processing": "transcribing",
}


def get_prefix(name: str) -> str:
    return PREFIXES.get(name, "")


def with_prefix(name: str, payload: Any) -> str:
    prefix = get_prefix(name)
    if not prefix:
        raise KeyError(f"Unknown IPC prefix key: {name}")
    if isinstance(payload, str):
        return f"{prefix}{payload}"
    return f"{prefix}{json.dumps(payload, separators=(',', ':'), ensure_ascii=False)}"


def is_prefixed_message(message: str, name: str) -> bool:
    if not isinstance(message, str):
        return False
    prefix = get_prefix(name)
    return bool(prefix and message.startswith(prefix))


def strip_prefix(message: str, name: str) -> Optional[str]:
    if not is_prefixed_message(message, name):
        return None
    return message[len(get_prefix(name)) :]


def validate_lifecycle_state(value: Any) -> bool:
    return isinstance(value, str) and value in VALID_LIFECYCLE_STATES


def validate_audio_state(value: Any) -> bool:
    return isinstance(value, str) and value in VALID_AUDIO_STATES


def derive_lifecycle_from_audio_state(audio_state: Any) -> str:
    if validate_audio_state(audio_state):
        return _AUDIO_TO_LIFECYCLE.get(str(audio_state), "idle")
    return "idle"


def normalize_audio_metrics_payload(
    payload: Any, *, expected_levels: int = 16
) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return None
    amplitude_raw = payload.get("amplitude", 0)
    try:
        amplitude = int(float(amplitude_raw))
    except (TypeError, ValueError):
        amplitude = 0
    amplitude = max(0, min(100, amplitude))

    levels_raw = payload.get("levels", [])
    levels: list[float] = []
    if isinstance(levels_raw, list):
        for value in levels_raw[:expected_levels]:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                numeric = 0.0
            levels.append(max(0.0, min(1.0, numeric)))

    if len(levels) < expected_levels:
        levels.extend([0.0] * (expected_levels - len(levels)))

    return {"amplitude": amplitude, "levels": levels}


def normalize_state_payload(
    payload: Any,
    *,
    defaults: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return None

    baseline = defaults or {}
    audio_state = payload.get("audioState", baseline.get("audioState", "inactive"))
    if not validate_audio_state(audio_state):
        audio_state = baseline.get("audioState", "inactive")
        if not validate_audio_state(audio_state):
            audio_state = "inactive"

    program_active = payload.get(
        "programActive", baseline.get("programActive", audio_state != "inactive")
    )
    program_active = bool(program_active)

    is_dictating = payload.get(
        "isDictating", baseline.get("isDictating", audio_state == "dictation")
    )
    is_dictating = bool(is_dictating)

    wake_word_enabled = payload.get(
        "wakeWordEnabled", baseline.get("wakeWordEnabled", True)
    )
    wake_word_enabled = bool(wake_word_enabled)

    lifecycle = payload.get(
        "dictationLifecycle",
        baseline.get("dictationLifecycle", derive_lifecycle_from_audio_state(audio_state)),
    )
    if not validate_lifecycle_state(lifecycle):
        lifecycle = derive_lifecycle_from_audio_state(audio_state)

    microphone_error = payload.get(
        "microphoneError", baseline.get("microphoneError", None)
    )
    if microphone_error is not None and not isinstance(microphone_error, str):
        microphone_error = str(microphone_error)

    current_mode = payload.get("currentMode", baseline.get("currentMode"))
    if current_mode is not None and not isinstance(current_mode, str):
        current_mode = str(current_mode)

    lifecycle_reason = payload.get(
        "dictationLifecycleReason", baseline.get("dictationLifecycleReason", "")
    )
    if not isinstance(lifecycle_reason, str):
        lifecycle_reason = str(lifecycle_reason)

    normalized = {
        "audioState": audio_state,
        "programActive": program_active,
        "isDictating": is_dictating,
        "wakeWordEnabled": wake_word_enabled,
        "currentMode": current_mode,
        "microphoneError": microphone_error,
        "dictationLifecycle": lifecycle,
        "dictationLifecycleReason": lifecycle_reason,
        "ipcSchemaVersion": IPC_SCHEMA_VERSION,
    }
    for key, value in payload.items():
        if key not in normalized:
            normalized[key] = value
    return normalized
