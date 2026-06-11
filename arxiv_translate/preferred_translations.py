from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PREFERRED_TRANSLATIONS_PATH = (
    Path(__file__).with_name("terminology") / "preferred_translations.md"
)
DEFAULT_PREFERRED_TRANSLATIONS = (
    ("mechanistic interpretability", "机制可解释性"),
)


@lru_cache(maxsize=1)
def load_preferred_translations() -> tuple[tuple[str, str], ...]:
    try:
        content = PREFERRED_TRANSLATIONS_PATH.read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_PREFERRED_TRANSLATIONS

    pairs: list[tuple[str, str]] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        columns = [part.strip() for part in line.strip("|").split("|")]
        if len(columns) < 2:
            continue
        english, chinese = columns[0], columns[1]
        if not english or not chinese:
            continue
        if english.lower() == "english term":
            continue
        if set(english) <= {"-"} and set(chinese) <= {"-"}:
            continue
        pairs.append((english, chinese))

    if not pairs:
        return DEFAULT_PREFERRED_TRANSLATIONS
    return tuple(_dedupe_preserving_order(pairs))


def format_preferred_translations_for_prompt() -> str:
    return "; ".join(f"`{english}` -> `{chinese}`" for english, chinese in load_preferred_translations())


def append_preferred_translations_section(guide: str) -> str:
    heading = "## Preferred Fixed Translations"
    if heading in guide:
        return guide
    rows = "\n".join(
        f"| {english} | {chinese} |"
        for english, chinese in load_preferred_translations()
    )
    suffix = (
        f"\n\n{heading}\n"
        "| English term | Preferred Chinese translation |\n"
        "| --- | --- |\n"
        f"{rows}\n"
    )
    return guide.rstrip() + suffix


def _dedupe_preserving_order(
    values: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    seen: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for english, chinese in values:
        key = english.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append((english, chinese))
    return deduped
