from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

_DEFAULT_OPENCLAW_SECRETS_PATH = Path.home() / ".openclaw" / "secrets.json"
_OPENCLAW_SECRETS_ENV_VARS = (
    "SCREENER_OPENCLAW_SECRETS_PATH",
    "OPENCLAW_SECRETS_PATH",
)


@dataclass(frozen=True, slots=True)
class OpenClawSecrets:
    values: Mapping[str, Any]

    def get(self, secret_path: str, default: Any = None) -> Any:
        normalized = _normalize_secret_path(secret_path)
        if not normalized:
            return default

        current: Any = self.values
        for part in normalized.split("/"):
            if not isinstance(current, Mapping) or part not in current:
                return default
            current = current[part]
        return current


def default_openclaw_secrets_path() -> Path:
    configured = next((os.getenv(name) for name in _OPENCLAW_SECRETS_ENV_VARS if os.getenv(name)), None)
    return Path(configured).expanduser() if configured else _DEFAULT_OPENCLAW_SECRETS_PATH


def load_openclaw_secrets(path: str | Path | None = None) -> OpenClawSecrets | None:
    secrets_path = Path(path).expanduser() if path is not None else default_openclaw_secrets_path()
    if not secrets_path.exists() or not secrets_path.is_file():
        return None

    try:
        payload = json.loads(secrets_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None
    return OpenClawSecrets(values=payload)


def _normalize_secret_path(secret_path: str) -> str:
    return "/".join(part for part in secret_path.strip().split("/") if part)
