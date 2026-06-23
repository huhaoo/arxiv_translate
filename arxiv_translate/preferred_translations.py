from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from .utils import unique_preserving_order

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
    return tuple(
        unique_preserving_order(pairs, key=lambda pair: pair[0].casefold())
    )


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
