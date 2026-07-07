from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import ArxivTranslateError

DEFAULT_CONFIG_PATH = "config.local.jsonc"
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
        data = json.loads(_normalize_jsonc(config_path.read_text(encoding="utf-8-sig")))
    except json.JSONDecodeError as exc:
        raise ArxivTranslateError(f"invalid JSONC config file: {config_path}") from exc

    if isinstance(data, list):
        raise ArxivTranslateError(
            "config file no longer supports multiple API entries; "
            f"replace the JSONC array with a single object: {config_path}"
        )
    if not isinstance(data, dict):
        raise ArxivTranslateError(
            f"config file must contain a JSONC object: {config_path}"
        )
    _validate_config(data)
    return data


def _normalize_jsonc(content: str) -> str:
    without_comments = _strip_jsonc_comments(content)
    return _strip_jsonc_trailing_commas(without_comments)


def _strip_jsonc_comments(content: str) -> str:
    chars: list[str] = []
    index = 0
    in_string = False
    escaped = False

    while index < len(content):
        char = content[index]
        next_char = content[index + 1] if index + 1 < len(content) else ""

        if in_string:
            chars.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            chars.append(char)
            index += 1
            continue

        if char == "/" and next_char == "/":
            index += 2
            while index < len(content) and content[index] not in "\r\n":
                index += 1
            continue

        if char == "/" and next_char == "*":
            index += 2
            while index < len(content) - 1:
                if content[index] == "*" and content[index + 1] == "/":
                    index += 2
                    break
                if content[index] in "\r\n":
                    chars.append(content[index])
                index += 1
            continue

        chars.append(char)
        index += 1

    return "".join(chars)


def _strip_jsonc_trailing_commas(content: str) -> str:
    chars: list[str] = []
    index = 0
    in_string = False
    escaped = False

    while index < len(content):
        char = content[index]

        if in_string:
            chars.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            chars.append(char)
            index += 1
            continue

        if char == ",":
            lookahead = index + 1
            while lookahead < len(content) and content[lookahead].isspace():
                lookahead += 1
            if lookahead < len(content) and content[lookahead] in "]}":
                index += 1
                continue

        chars.append(char)
        index += 1

    return "".join(chars)


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
