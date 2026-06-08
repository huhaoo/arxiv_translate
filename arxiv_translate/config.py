from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import ArxivTranslateError

DEFAULT_CONFIG_PATH = "config.local.json"
REQUIRED_CONFIG_FIELDS = (
    "deepseek_api_key",
    "deepseek_model",
    "deepseek_guide_model",
    "deepseek_appendix_model",
    "deepseek_base_url",
)


def load_config(path: str | Path) -> list[dict[str, Any]]:
    config_path = Path(path)
    if not config_path.exists():
        raise ArxivTranslateError(f"config file not found: {config_path}")

    try:
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ArxivTranslateError(f"invalid JSON config file: {config_path}") from exc

    if not isinstance(data, list):
        raise ArxivTranslateError(
            f"config file must contain a JSON array of objects: {config_path}"
        )
    if not data:
        raise ArxivTranslateError(f"config file must contain at least one config: {config_path}")
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ArxivTranslateError(
                f"config item #{index} must be a JSON object: {config_path}"
            )
        _validate_config_item(item, index)
    return data


def config_string(
    config: dict[str, Any],
    key: str,
    index: int,
    *,
    allow_empty: bool = False,
) -> str:
    if key not in config:
        raise ArxivTranslateError(f"missing required config field in item #{index}: {key}")
    value = config[key]
    if isinstance(value, str) and (value or allow_empty):
        return value
    raise ArxivTranslateError(f"missing required config field in item #{index}: {key}")


def _validate_config_item(config: dict[str, Any], index: int) -> None:
    for key in REQUIRED_CONFIG_FIELDS:
        config_string(config, key, index, allow_empty=key == "deepseek_api_key")
