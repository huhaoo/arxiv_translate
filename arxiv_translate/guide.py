from __future__ import annotations

from pathlib import Path

from .deepseek import DeepSeekClient


def load_or_generate_paper_guide(
    source_dir: Path,
    guide_path: Path,
    client: DeepSeekClient,
) -> str:
    if guide_path.exists():
        return guide_path.read_text(encoding="utf-8")

    latex_document = collect_latex_document(source_dir)
    guide = client.generate_paper_guide(latex_document)
    guide_path.parent.mkdir(parents=True, exist_ok=True)
    guide_path.write_text(guide, encoding="utf-8", newline="\n")
    return guide


def collect_latex_document(source_dir: Path) -> str:
    parts: list[str] = []
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".tex", ".ltx"}:
            continue
        relative = path.relative_to(source_dir).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        parts.append(f"<LATEX_FILE path=\"{relative}\">\n{text}\n</LATEX_FILE>")
    return "\n\n".join(parts)
