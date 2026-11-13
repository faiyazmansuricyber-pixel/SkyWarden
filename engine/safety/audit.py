from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_AUDIT_PATH = ROOT_DIR / "data" / "audit.jsonl"
SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
    "apikey",
)


def _is_sensitive_key(key: str) -> bool:
    normalized_key = key.lower().replace("-", "").replace("_", "")
    return any(part in normalized_key for part in SENSITIVE_KEY_PARTS)


def _redact(value: Any, key: str = "") -> Any:
    if _is_sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(child_key): _redact(child, str(child_key)) for child_key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(child) for child in value]
    return value


def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        name: (
            "[REDACTED]"
            if _is_sensitive_key(name)
            else value
        )
        for name, value in headers.items()
    }


class AuditLog:
    def __init__(self, path: Path = DEFAULT_AUDIT_PATH) -> None:
        self.path = path
        self._lock = Lock()

    def append(self, record: Mapping[str, object]) -> None:
        payload = dict(record)
        payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        safe_payload = _redact(payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.path.open("a", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(safe_payload, separators=(",", ":"), sort_keys=True))
            output.write("\n")
