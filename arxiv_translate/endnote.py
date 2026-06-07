from __future__ import annotations

from pathlib import Path

from .metadata import ArxivMetadata


def write_endnote_import(
    metadata: ArxivMetadata,
    destination: Path,
    attachments: list[Path],
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        format_endnote_import(metadata, attachments),
        encoding="utf-8-sig",
        newline="\n",
    )
    return destination


def format_endnote_import(metadata: ArxivMetadata, attachments: list[Path]) -> str:
    lines = [
        "%0 Electronic Article",
        *[f"%A {author}" for author in metadata.authors],
        f"%T {metadata.title}",
        f"%D {metadata.year}",
        f"%8 {metadata.published[:10]}",
        "%J arXiv",
        f"%U {metadata.abs_url}",
        f"%M arXiv:{metadata.arxiv_id}",
        f"%X {metadata.abstract}",
    ]

    if metadata.doi:
        lines.append(f"%R {metadata.doi}")
    if metadata.journal_ref:
        lines.append(f"%O {metadata.journal_ref}")
    if metadata.primary_category:
        lines.append(f"%9 {metadata.primary_category}")
    if metadata.comment:
        lines.append(f"%Z {metadata.comment}")
    for category in metadata.categories:
        lines.append(f"%K {category}")
    for attachment in attachments:
        if attachment.exists():
            lines.append(f"%> {attachment.resolve().as_uri()}")

    return "\n".join(_clean_line(line) for line in lines) + "\n\n"


def _clean_line(line: str) -> str:
    return line.replace("\r", " ").replace("\n", " ")
