from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path

LATEX_DOCUMENT_SUFFIXES = frozenset({".tex", ".ltx"})
LATEX_STYLE_SUFFIXES = frozenset({".sty", ".cls"})
LATEX_DEFINITION_SUFFIXES = LATEX_DOCUMENT_SUFFIXES | LATEX_STYLE_SUFFIXES


def iter_source_files(root: Path, suffixes: Iterable[str]) -> Iterator[Path]:
    normalized_suffixes = frozenset(suffix.lower() for suffix in suffixes)
    return (
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix.lower() in normalized_suffixes
    )


def iter_latex_documents(root: Path) -> Iterator[Path]:
    return iter_source_files(root, LATEX_DOCUMENT_SUFFIXES)


def contains_latex_document(root: Path) -> bool:
    return any(
        path.is_file() and path.suffix.lower() in LATEX_DOCUMENT_SUFFIXES
        for path in root.rglob("*")
    )
