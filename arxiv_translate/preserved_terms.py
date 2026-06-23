from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from .utils import unique_preserving_order

PRESERVED_TERMS_PATH = Path(__file__).with_name("terminology") / "preserved_terms.md"
DEFAULT_PRESERVED_TERMS = (
    "token",
    "scaling law",
)
_CODE_SPAN_RE = re.compile(r"`([^`]+)`")


@lru_cache(maxsize=1)
def load_preserved_terms() -> tuple[str, ...]:
    try:
        content = PRESERVED_TERMS_PATH.read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_PRESERVED_TERMS

    terms: list[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line.startswith("- "):
            continue
        body = line[2:].strip()
        match = _CODE_SPAN_RE.search(body)
        term = match.group(1).strip() if match else body
        if term:
            terms.append(term)

    if not terms:
        return DEFAULT_PRESERVED_TERMS
    return tuple(unique_preserving_order(terms, key=str.casefold))


def format_preserved_terms_for_prompt() -> str:
    terms = load_preserved_terms()
    return ", ".join(f"`{term}`" for term in terms)


def append_preserved_terms_section(guide: str) -> str:
    terms = load_preserved_terms()
    heading = "## Forced Keep-English Terms"
    if heading in guide:
        return guide
    bullets = "\n".join(f"- `{term}`" for term in terms)
    suffix = f"\n\n{heading}\n{bullets}\n"
    return guide.rstrip() + suffix


def strip_preserved_terms(content: str) -> str:
    stripped = content
    for term in load_preserved_terms():
        pattern = re.compile(rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])", re.IGNORECASE)
        stripped = pattern.sub(" ", stripped)
    return stripped
