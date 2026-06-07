from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import ArxivTranslateError

DEFAULT_CONFIG_PATH = "config.local.json"


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise ArxivTranslateError(f"config file not found: {config_path}")

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ArxivTranslateError(f"invalid JSON config file: {config_path}") from exc

    if not isinstance(data, dict):
        raise ArxivTranslateError(f"config file must contain a JSON object: {config_path}")
    return data


def config_string(config: dict[str, Any], key: str) -> str:
    value = config.get(key)
    if isinstance(value, str) and value:
        return value
    raise ArxivTranslateError(f"missing required config field: {key}")
