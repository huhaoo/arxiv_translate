from __future__ import annotations

import re
from pathlib import Path

VERBATIM_ENVIRONMENTS = {
    "alltt",
    "filecontents",
    "filecontents*",
    "lstlisting",
    "minted",
    "Verbatim",
    "verbatim",
}
BEGIN_ENV_RE = re.compile(r"\\begin\{([^}]+)\}")
END_ENV_RE = re.compile(r"\\end\{([^}]+)\}")
TITLE_COMMAND_RE = re.compile(r"(?<!\\)\\title\b")
PDF_TITLE_ASSIGNMENT_RE = re.compile(r"(?<![A-Za-z])(?:Title|pdftitle)\s*=\s*\{")
HYPERREF_PACKAGE_RE = re.compile(
    r"(?m)^(?P<indent>\s*)\\usepackage(?:\[[^\]]*\])?\{hyperref\}(?P<tail>\s*(?:%.*)?)$"
)
BEGIN_DOCUMENT_RE = re.compile(r"(?<!\\)\\begin\{document\}")
NATBIB_STYLE_SNIPPET = (
    "% arxiv-translate: superscript numeric citations\n"
    "\\makeatletter\n"
    "\\@ifpackageloaded{natbib}{%\n"
    "  \\citestyle{numeric}%\n"
    "  \\setcitestyle{numbers,sort&compress}%\n"
    "  \\renewcommand{\\cite}[1]{\\textsuperscript{[\\citealp{#1}]}}%\n"
    "  \\renewcommand{\\citep}[1]{\\textsuperscript{[\\citealp{#1}]}}%\n"
    "  \\renewcommand{\\citet}[1]{\\textsuperscript{[\\citealp{#1}]}}%\n"
    "}{%\n"
    "  \\def\\citepunct{, }%\n"
    "  \\def\\citedash{--}%\n"
    "  \\let\\@axtoldcite\\cite%\n"
    "  \\def\\cite{\\@ifnextchar[{\\@axtcite}{\\@axtcite[]}}%\n"
    "  \\def\\@axtcite[#1]#2{\\textsuperscript{\\@axtoldcite[#1]{#2}}}%\n"
    "}\n"
    "\\makeatother\n"
)
NATBIB_AUTHORYEAR_REPLACEMENTS = {
    r"\setcitestyle{authoryear,round,citesep={;},aysep={,},yysep={;}}": r"\setcitestyle{numbers,sort&compress}",
    r"\citestyle{authoryear}": r"\citestyle{numeric}",
}
TEXT_BOX_COMMANDS = {
    "fbox": 1,
    "framebox": 1,
    "makebox": 1,
    "colorbox": 2,
    "fcolorbox": 3,
    "parbox": 2,
    "tcbox": 1,
}
GLOSSARY_KEY_COMMANDS = {
    "term": 1,
    "gls": 1,
    "Gls": 1,
    "glspl": 1,
    "Glspl": 1,
    "acrshort": 1,
    "Acrshort": 1,
    "acrfull": 1,
    "Acrfull": 1,
    "acrshortpl": 1,
    "Acrshortpl": 1,
}
PROTECTED_TEXT_BOX_RE = re.compile(r"\\AXTProtectedTextBox\s*\{\s*(\d+)\s*\}")


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


def strip_latex_comments(text: str) -> str:
    """Remove TeX comments while preserving escaped percent signs and code blocks."""

    output: list[str] = []
    verbatim_stack: list[str] = []
    for line in text.splitlines(keepends=True):
        if verbatim_stack:
            output.append(line)
            _update_verbatim_stack(line, verbatim_stack)
            continue

        stripped = _strip_latex_comment_from_line(line)
        output.append(stripped)
        _update_verbatim_stack(stripped, verbatim_stack)
    return "".join(output)


def protect_latex_text_boxes(text: str) -> tuple[str, list[str]]:
    """Replace fragile LaTeX regions with placeholders before translation."""

    spans = _merge_spans(_find_text_box_spans(text) + _find_glossary_key_spans(text))
    if not spans:
        return text, []

    protected: list[str] = []
    blocks: list[str] = []
    cursor = 0
    for start, end in spans:
        protected.append(text[cursor:start])
        blocks.append(text[start:end])
        protected.append(rf"\AXTProtectedTextBox{{{len(blocks) - 1}}}")
        cursor = end
    protected.append(text[cursor:])
    return "".join(protected), blocks


def restore_latex_text_boxes(text: str, blocks: list[str]) -> str:
    """Restore placeholders created by protect_latex_text_boxes."""

    if not blocks:
        return text

    def replace(match: re.Match[str]) -> str:
        index = int(match.group(1))
        if 0 <= index < len(blocks):
            return blocks[index]
        return match.group(0)

    return PROTECTED_TEXT_BOX_RE.sub(replace, text)


def _find_text_box_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(text):
        if text[index] != "\\":
            index += 1
            continue
        match = re.match(r"\\([A-Za-z]+)\*?", text[index:])
        if match is None:
            index += 1
            continue
        command = match.group(1)
        required_args = TEXT_BOX_COMMANDS.get(command)
        if required_args is None:
            index += len(match.group(0))
            continue
        end = _parse_box_command_end(text, index + len(match.group(0)), required_args)
        if end is None:
            index += len(match.group(0))
            continue
        spans.append((index, end))
        index = end
    return spans


def _find_glossary_key_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(text):
        if text[index] != "\\":
            index += 1
            continue
        match = re.match(r"\\([A-Za-z]+)\*?", text[index:])
        if match is None:
            index += 1
            continue
        command = match.group(1)
        required_args = GLOSSARY_KEY_COMMANDS.get(command)
        if required_args is None:
            index += len(match.group(0))
            continue
        end = _parse_command_end(text, index + len(match.group(0)), required_args)
        if end is None:
            index += len(match.group(0))
            continue
        spans.append((index, end))
        index = end
    return spans


def _parse_box_command_end(text: str, start: int, required_args: int) -> int | None:
    return _parse_command_end(text, start, required_args)


def _parse_command_end(text: str, start: int, required_args: int) -> int | None:
    index = start
    required_seen = 0
    while index < len(text):
        index = _skip_whitespace(text, index)
        if index >= len(text):
            return None
        if text[index] == "[":
            end = _find_balanced_end(text, index, "[", "]")
            if end is None:
                return None
            index = end
            continue
        if text[index] != "{":
            return None
        end = _find_balanced_end(text, index, "{", "}")
        if end is None:
            return None
        required_seen += 1
        index = end
        if required_seen >= required_args:
            return index
    return None


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not spans:
        return []
    ordered = sorted(spans)
    merged: list[list[int]] = [[ordered[0][0], ordered[0][1]]]
    for start, end in ordered[1:]:
        current = merged[-1]
        if start <= current[1]:
            current[1] = max(current[1], end)
            continue
        merged.append([start, end])
    return [(start, end) for start, end in merged]


def ensure_english_pdf_title(
    translated_main_tex: Path,
    original_main_tex: Path,
    fallback_title: str,
) -> bool:
    """Keep the translated PDF's visible title equal to the English source title."""

    translated = translated_main_tex.read_text(encoding="utf-8", errors="ignore")
    original = original_main_tex.read_text(encoding="utf-8", errors="ignore")

    updated = translated
    pdf_title_assignment = extract_pdf_title_assignment(original)
    if pdf_title_assignment is None and fallback_title:
        pdf_title_assignment = f"pdftitle={{{escape_latex_title_text(fallback_title)}}}"
    if pdf_title_assignment is not None:
        updated = replace_pdf_title_assignment(updated, pdf_title_assignment)

    title_command = extract_latex_title_command(original)
    if title_command is not None and _title_command_has_content(title_command):
        updated = replace_latex_title_command(updated, title_command)
    elif fallback_title and extract_latex_title_command(updated) is not None:
        updated = replace_latex_title_command(
            updated,
            rf"\title{{{escape_latex_title_text(fallback_title)}}}",
            insert_if_missing=False,
        )

    if updated == translated:
        return False
    translated_main_tex.write_text(updated, encoding="utf-8")
    return True


_CITE_CMD = r"\\cite(?:p|t|alp|alt|author|year|yearpar)?\*?(?:\[[^\]]*\])?\{([^{}]*)\}"
_ADJACENT_CITE_PAIR_RE = re.compile(
    rf"(?P<first>{_CITE_CMD})"
    rf"(?P<sep>\s*(?:[,;，；、]\s*)?(?:and|or|和|与|及|以及|或|或者)?\s*)"
    rf"(?P<second>{_CITE_CMD})"
)


def merge_adjacent_citations(text: str) -> str:
    """Merge adjacent \\cite-like commands so they render in a single bracket.

    \\cite{a}\\cite{b}   ->  \\cite{a,b}
    \\cite{a}, \\cite{b}  ->  \\cite{a,b}
    \\citep{a} \\citet{b} ->  \\cite{a,b}
    """

    def _merge(match: re.Match[str]) -> str:
        keys1 = match.group(2).strip()
        keys2 = match.group(5).strip()
        merged_keys = f"{keys1},{keys2}" if keys1 and keys2 else (keys1 or keys2)
        return r"\cite{" + merged_keys + "}"

    changed = True
    while changed:
        new_text = _ADJACENT_CITE_PAIR_RE.sub(_merge, text)
        changed = new_text != text
        text = new_text
    return text


def merge_adjacent_citations_in_dir(root: Path) -> list[Path]:
    """Run merge_adjacent_citations on every .tex / .ltx file under *root*.

    Returns the list of files that were modified.
    """

    updated: list[Path] = []
    for pattern in ("*.tex", "*.ltx"):
        for path in root.rglob(pattern):
            original = path.read_text(encoding="utf-8", errors="ignore")
            merged = merge_adjacent_citations(original)
            if merged == original:
                continue
            path.write_text(merged, encoding="utf-8", newline="")
            updated.append(path)
    return updated


def ensure_superscript_numeric_citations(main_tex: Path) -> bool:
    """Prefer superscript numeric natbib citations like ^[1,2]."""

    text = main_tex.read_text(encoding="utf-8", errors="ignore")
    if "% arxiv-translate: superscript numeric citations" in text:
        return False
    if r"\setcitestyle{numbers,sort&compress,super,open={[},close={]}}" in text:
        return False

    begin_document = BEGIN_DOCUMENT_RE.search(text)
    if begin_document is None:
        return False

    updated = text[: begin_document.start()] + NATBIB_STYLE_SNIPPET + text[begin_document.start() :]
    if updated == text:
        return False
    main_tex.write_text(updated, encoding="utf-8", newline="")
    return True


def ensure_numeric_natbib_styles(root: Path) -> list[Path]:
    """Normalize natbib style files so templates do not force author-year citations."""

    updated_files: list[Path] = []
    for pattern in ("*.sty", "*.cls"):
        for path in root.rglob(pattern):
            text = path.read_text(encoding="utf-8", errors="ignore")
            updated = text
            for source, target in NATBIB_AUTHORYEAR_REPLACEMENTS.items():
                updated = updated.replace(source, target)
            if updated == text:
                continue
            path.write_text(updated, encoding="utf-8", newline="")
            updated_files.append(path)
    return updated_files


def extract_latex_title_command(text: str) -> str | None:
    span = _find_latex_title_span(text)
    if span is None:
        return None
    return text[span[0] : span[1]]


def replace_latex_title_command(
    text: str,
    title_command: str,
    *,
    insert_if_missing: bool = True,
) -> str:
    span = _find_latex_title_span(text)
    if span is not None:
        return text[: span[0]] + title_command + text[span[1] :]

    if not insert_if_missing:
        return text

    begin_document = BEGIN_DOCUMENT_RE.search(text)
    if begin_document:
        insertion = title_command.rstrip() + "\n"
        return text[: begin_document.start()] + insertion + text[begin_document.start() :]
    return text


def extract_pdf_title_assignment(text: str) -> str | None:
    span = _find_pdf_title_assignment_span(text)
    if span is None:
        return None
    return text[span[0] : span[1]]


def replace_pdf_title_assignment(text: str, title_assignment: str) -> str:
    span = _find_pdf_title_assignment_span(text)
    if span is not None:
        return text[: span[0]] + title_assignment + text[span[1] :]

    hypersetup = f"\\hypersetup{{{title_assignment}}}\n"
    match = HYPERREF_PACKAGE_RE.search(text)
    if match is not None:
        return text[: match.end()] + "\n" + hypersetup + text[match.end() :]

    match = BEGIN_DOCUMENT_RE.search(text)
    if match is None:
        return text
    return text[: match.start()] + "\\usepackage{hyperref}\n" + hypersetup + text[match.start() :]


def escape_latex_title_text(title: str) -> str:
    """Escape plain arXiv metadata title text while preserving simple $...$ math."""

    escaped: list[str] = []
    in_math = False
    i = 0
    while i < len(title):
        char = title[i]
        if char == "$" and (i == 0 or title[i - 1] != "\\"):
            in_math = not in_math
            escaped.append(char)
        elif not in_math and char in {"&", "%", "#", "_", "{", "}"}:
            escaped.append("\\" + char)
        else:
            escaped.append(char)
        i += 1
    return "".join(escaped)


def _find_latex_title_span(text: str) -> tuple[int, int] | None:
    for match in TITLE_COMMAND_RE.finditer(text):
        end = _parse_title_command_end(text, match.end())
        if end is not None:
            return match.start(), end
    return None


def _find_pdf_title_assignment_span(text: str) -> tuple[int, int] | None:
    for match in PDF_TITLE_ASSIGNMENT_RE.finditer(text):
        brace_start = match.end() - 1
        end = _find_balanced_end(text, brace_start, "{", "}")
        if end is not None:
            return match.start(), end
    return None


def _title_command_has_content(title_command: str) -> bool:
    span = _find_latex_title_span(title_command)
    if span is None:
        return False

    command_start, command_end = span
    index = title_command.find("{", command_start, command_end)
    if index == -1:
        return False
    content = title_command[index + 1 : command_end - 1]
    return bool(content.strip())


def _parse_title_command_end(text: str, start: int) -> int | None:
    index = _skip_whitespace(text, start)
    while index < len(text) and text[index] == "[":
        end = _find_balanced_end(text, index, "[", "]")
        if end is None:
            return None
        index = _skip_whitespace(text, end)

    if index >= len(text) or text[index] != "{":
        return None
    return _find_balanced_end(text, index, "{", "}")


def _find_balanced_end(text: str, start: int, open_char: str, close_char: str) -> int | None:
    depth = 0
    index = start
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return None


def _skip_whitespace(text: str, start: int) -> int:
    index = start
    while index < len(text) and text[index].isspace():
        index += 1
    return index


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


def _strip_latex_comment_from_line(line: str) -> str:
    i = 0
    while i < len(line):
        if line[i] == "%" and not _is_escaped_percent(line, i):
            if not line[:i].strip():
                return ""
            newline = _line_ending(line)
            return line[:i].rstrip() + newline
        i += 1
    return line


def _is_escaped_percent(line: str, index: int) -> bool:
    backslashes = 0
    cursor = index - 1
    while cursor >= 0 and line[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


def _line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    if line.endswith("\r"):
        return "\r"
    return ""


def _update_verbatim_stack(line: str, stack: list[str]) -> None:
    for match in re.finditer(r"\\(?:begin|end)\{([^}]+)\}", line):
        env_name = match.group(1)
        if env_name not in VERBATIM_ENVIRONMENTS:
            continue
        if match.group(0).startswith(r"\begin"):
            stack.append(env_name)
        elif stack and stack[-1] == env_name:
            stack.pop()


def should_translate_tex(text: str) -> bool:
    letters = sum(1 for char in text if "A" <= char <= "Z" or "a" <= char <= "z")
    return letters >= 20
