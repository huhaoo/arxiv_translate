from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import ArxivTranslateError

DEFAULT_CONFIG_PATH = "config.local.json"
REQUIRED_CONFIG_FIELDS = (
    "deepseek_api_key",
    "deepseek_model",
    "deepseek_appendix_model",
    "deepseek_base_url",
)


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise ArxivTranslateError(f"config file not found: {config_path}")

    try:
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ArxivTranslateError(f"invalid JSON config file: {config_path}") from exc

    if isinstance(data, list):
        raise ArxivTranslateError(
            "config file no longer supports multiple API entries; "
            f"replace the JSON array with a single object: {config_path}"
        )
    if not isinstance(data, dict):
        raise ArxivTranslateError(
            f"config file must contain a JSON object: {config_path}"
        )
    _validate_config(data)
    return data


def config_string(
    config: dict[str, Any],
    key: str,
    *,
    allow_empty: bool = False,
) -> str:
    if key not in config:
        raise ArxivTranslateError(f"missing required config field: {key}")
    value = config[key]
    if isinstance(value, str) and (value or allow_empty):
        return value
    raise ArxivTranslateError(f"missing required config field: {key}")


def config_bool(
    config: dict[str, Any],
    key: str,
    *,
    default: bool,
) -> bool:
    if key not in config:
        return default
    value = config[key]
    if isinstance(value, bool):
        return value
    raise ArxivTranslateError(f"config field must be true or false: {key}")


def _validate_config(config: dict[str, Any]) -> None:
    for key in REQUIRED_CONFIG_FIELDS:
        config_string(config, key, allow_empty=key == "deepseek_api_key")
    config_bool(config, "use_proxy", default=True)
