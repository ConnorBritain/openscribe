"""Shared settings schema helpers backed by shared/settings_contract.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

_CONTRACT_PATH = Path(__file__).resolve().parents[1] / "shared" / "settings_contract.json"

_DEFAULT_CONTRACT: Dict[str, Any] = {
    "version": 1,
    "keys": [],
    "electronDefaults": {},
    "pythonDefaults": {},
    "pythonConfigKeys": [],
    "pythonConfigOptionalStringKeys": [],
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
SETTINGS_SCHEMA_VERSION: int = int(CONTRACT.get("version", 1))
SETTINGS_KEYS: List[str] = list(CONTRACT.get("keys", []) or [])
ELECTRON_DEFAULTS: Dict[str, Any] = dict(CONTRACT.get("electronDefaults", {}) or {})
PYTHON_DEFAULTS: Dict[str, Any] = dict(CONTRACT.get("pythonDefaults", {}) or {})
PYTHON_CONFIG_KEYS: List[str] = list(CONTRACT.get("pythonConfigKeys", []) or [])
PYTHON_CONFIG_OPTIONAL_STRING_KEYS: List[str] = list(
    CONTRACT.get("pythonConfigOptionalStringKeys", []) or []
)
