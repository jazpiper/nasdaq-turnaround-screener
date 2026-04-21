from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_text(path: Path, content: str) -> Path:
    ensure_directory(path.parent)
    path.write_text(content, encoding="utf-8")
    return path


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    ensure_directory(path.parent)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path
