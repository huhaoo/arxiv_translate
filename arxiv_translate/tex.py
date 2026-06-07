from __future__ import annotations

import re
from pathlib import Path


def discover_main_tex(root: Path, explicit: str | None = None) -> Path:
    if explicit:
        main = root / explicit
        if not main.exists():
            raise FileNotFoundError(f"main TeX file not found: {main}")
        return main

    candidates: list[tuple[int, Path]] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".tex", ".ltx"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        score = 0
        if "\\documentclass" in text:
            score -= 100
        if "\\begin{document}" in text:
            score -= 50
        if path.parent == root:
            score -= 20
        if path.name.lower() in {"main.tex", "paper.tex", "ms.tex", "article.tex"}:
            score -= 10
        score += len(path.parts)
        candidates.append((score, path))

    if not candidates:
        raise FileNotFoundError("no TeX files found")
    return sorted(candidates, key=lambda item: (item[0], str(item[1])))[0][1]


def split_latex_for_translation(text: str, max_chars: int) -> list[str]:
    """Split TeX into paragraph-ish chunks without breaking paired syntax."""

    if len(text) <= max_chars:
        return [text]

    paragraphs = re.split(r"(\n\s*\n)", text)
    chunks: list[str] = []
    current = ""
    for part in paragraphs:
        if not current:
            current = part
            continue

        if len(current) + len(part) <= max_chars or not _is_safe_latex_boundary(current):
            current += part
            if len(current) >= max_chars and _is_safe_latex_boundary(current):
                chunks.append(current)
                current = ""
            continue

        chunks.append(current)
        current = part
    if current:
        chunks.append(current)
    return chunks


def _is_safe_latex_boundary(text: str) -> bool:
    brace_depth = 0
    bracket_depth = 0
    env_stack: list[str] = []
    dollar_math = False
    double_dollar_math = False
    slash_math: str | None = None
    in_comment = False
    i = 0

    while i < len(text):
        char = text[i]
        previous = text[i - 1] if i > 0 else ""

        if in_comment:
            if char == "\n":
                in_comment = False
            i += 1
            continue

        if char == "%" and previous != "\\":
            in_comment = True
            i += 1
            continue

        begin_env = _read_environment_command(text, i, "begin")
        if begin_env is not None:
            if begin_env != "document":
                env_stack.append(begin_env)
            i += len(r"\begin{") + len(begin_env) + 1
            continue

        end_env = _read_environment_command(text, i, "end")
        if end_env is not None:
            if end_env != "document":
                if not env_stack or env_stack[-1] != end_env:
                    return False
                env_stack.pop()
            i += len(r"\end{") + len(end_env) + 1
            continue

        if text.startswith(r"\(", i):
            slash_math = "paren"
            i += 2
            continue
        if text.startswith(r"\)", i) and slash_math == "paren":
            slash_math = None
            i += 2
            continue
        if text.startswith(r"\[", i):
            slash_math = "bracket"
            i += 2
            continue
        if text.startswith(r"\]", i) and slash_math == "bracket":
            slash_math = None
            i += 2
            continue

        if char == "$" and previous != "\\":
            if i + 1 < len(text) and text[i + 1] == "$":
                double_dollar_math = not double_dollar_math
                i += 2
                continue
            if not double_dollar_math:
                dollar_math = not dollar_math

        if previous == "\\":
            i += 1
            continue

        in_math = dollar_math or double_dollar_math or slash_math is not None

        if char == "{":
            brace_depth += 1
        elif char == "}":
            brace_depth -= 1
            if brace_depth < 0:
                return False
        elif char == "[" and not in_math:
            bracket_depth += 1
        elif char == "]" and not in_math:
            bracket_depth -= 1
            if bracket_depth < 0:
                return False

        i += 1

    return (
        brace_depth == 0
        and bracket_depth == 0
        and not env_stack
        and not dollar_math
        and not double_dollar_math
        and slash_math is None
    )


def _read_environment_command(text: str, start: int, command: str) -> str | None:
    prefix = f"\\{command}{{"
    if not text.startswith(prefix, start):
        return None
    end = text.find("}", start + len(prefix))
    if end == -1:
        return None
    env_name = text[start + len(prefix) : end]
    return env_name or None


def should_translate_tex(text: str) -> bool:
    letters = sum(1 for char in text if "A" <= char <= "Z" or "a" <= char <= "z")
    return letters >= 20
