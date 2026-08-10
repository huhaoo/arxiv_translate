from __future__ import annotations

import re
from pathlib import Path

from .latex_scan import (
    balanced_group_end,
    is_escaped,
    line_ending,
    skip_whitespace,
)
from .source_files import (
    LATEX_STYLE_SUFFIXES,
    iter_latex_documents,
    iter_source_files,
)

VERBATIM_ENVIRONMENTS = {
    "alltt",
    "filecontents",
    "filecontents*",
    "lstlisting",
    "minted",
    # These are custom tcolorbox listing environments used by several arXiv
    # sources for executable prompts and examples.  Their contents may contain
    # Markdown (notably literal '#') and template braces, so they must not be
    # sent through prose translation.
    "prompt",
    "case",
    "Verbatim",
    "verbatim",
}
BEGIN_ENV_RE = re.compile(r"\\begin\{([^}]+)\}")
TITLE_COMMAND_RE = re.compile(r"(?<!\\)\\title\b")
DATE_COMMAND_RE = re.compile(r"(?<!\\)\\date\b")
PDF_TITLE_ASSIGNMENT_RE = re.compile(r"(?<![A-Za-z])(?:Title|pdftitle)\s*=\s*\{")
PDF_METADATA_TITLE_MARKER = "% arxiv-translate: PDF metadata title"
HYPERREF_PACKAGE_RE = re.compile(
    r"(?m)^(?P<indent>\s*)\\usepackage(?:\[[^\]]*\])?\{hyperref\}(?P<tail>\s*(?:%.*)?)$"
)
BEGIN_DOCUMENT_RE = re.compile(r"(?<!\\)\\begin\{document\}")
LATEX_OPTION_LIST_START_RE = re.compile(
    r"\\[A-Za-z@]+\*?(?:\{[^{}\r\n]*\})?\s*\["
)
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
LATEX_ACCENT_COMMANDS = {
    '"',
    "'",
    "`",
    "^",
    "~",
    "=",
    ".",
    "b",
    "c",
    "d",
    "H",
    "k",
    "r",
    "t",
    "u",
    "v",
}
LATEX_ACCENT_RE = re.compile(
    r"\\(?:(?P<symbol>[\"'`\^~=\.])\s*"
    r"(?:\{(?P<braced_symbol>[A-Za-z])\}|(?P<char_symbol>[A-Za-z]))"
    r"|(?P<word>b|c|d|H|k|r|t|u|v)"
    r"(?:\s*\{(?P<braced_word>[A-Za-z])\}|\s+(?P<char_word>[A-Za-z])))"
)


def discover_main_tex(root: Path, explicit: str | None = None) -> Path:
    if explicit:
        main = root / explicit
        if not main.exists():
            raise FileNotFoundError(f"main TeX file not found: {main}")
        return main

    candidates: list[tuple[int, Path]] = []
    for path in iter_latex_documents(root):
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
    optional_depth = 0
    for line in text.splitlines(keepends=True):
        if verbatim_stack:
            output.append(line)
            _update_verbatim_stack(line, verbatim_stack)
            continue

        stripped = _strip_latex_comment_from_line(line)
        if optional_depth > 0 and not stripped.strip():
            continue
        output.append(stripped)
        _update_verbatim_stack(stripped, verbatim_stack)
        optional_depth = _updated_optional_argument_depth(stripped, optional_depth)
    return "".join(output)


def normalize_latex_text_accents(text: str) -> str:
    """Remove fragile LaTeX text accents before prose translation.

    This keeps commands like ``na\"ively`` from being split into invalid
    control sequences during translation. Verbatim-like environments are left
    untouched.
    """

    output: list[str] = []
    verbatim_stack: list[str] = []
    for line in text.splitlines(keepends=True):
        if verbatim_stack:
            output.append(line)
            _update_verbatim_stack(line, verbatim_stack)
            continue

        normalized = LATEX_ACCENT_RE.sub(_replace_latex_text_accent, line)
        output.append(normalized)
        _update_verbatim_stack(normalized, verbatim_stack)
    return "".join(output)


def protect_latex_text_boxes(text: str) -> tuple[str, list[str]]:
    """Replace fragile LaTeX regions with placeholders before translation."""

    spans = _merge_spans(
        _find_verbatim_environment_spans(text)
        + _find_text_box_spans(text)
        + _find_glossary_key_spans(text)
    )
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


def _replace_latex_text_accent(match: re.Match[str]) -> str:
    accent = match.group("symbol") or match.group("word")
    if accent not in LATEX_ACCENT_COMMANDS:
        return match.group(0)
    return (
        match.group("braced_symbol")
        or match.group("char_symbol")
        or match.group("braced_word")
        or match.group("char_word")
        or match.group(0)
    )


def _find_verbatim_environment_spans(text: str) -> list[tuple[int, int]]:
    """Find code/verbatim environments that must bypass translation entirely."""

    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(text):
        match = BEGIN_ENV_RE.search(text, index)
        if match is None:
            break
        env_name = match.group(1)
        if env_name not in VERBATIM_ENVIRONMENTS:
            index = match.end()
            continue

        end_marker = rf"\end{{{env_name}}}"
        end_start = text.find(end_marker, match.end())
        if end_start == -1:
            index = match.end()
            continue
        end = end_start + len(end_marker)
        spans.append((match.start(), end))
        index = end
    return spans


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
        end = _parse_command_end(text, index + len(match.group(0)), required_args)
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


def _parse_command_end(text: str, start: int, required_args: int) -> int | None:
    index = start
    required_seen = 0
    while index < len(text):
        index = skip_whitespace(text, index)
        if index >= len(text):
            return None
        if text[index] == "[":
            end = balanced_group_end(text, index, "[", "]")
            if end is None:
                return None
            index = end
            continue
        if text[index] != "{":
            return None
        end = balanced_group_end(text, index, "{", "}")
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
    arxiv_id: str = "",
) -> bool:
    """Keep the visible English title and add the arXiv ID to PDF metadata."""

    translated = translated_main_tex.read_text(encoding="utf-8", errors="ignore")
    original = original_main_tex.read_text(encoding="utf-8", errors="ignore")

    updated = translated
    pdf_title_assignment = extract_pdf_title_assignment(original)
    if pdf_title_assignment is None and fallback_title:
        pdf_title_assignment = f"pdftitle={{{escape_latex_title_text(fallback_title)}}}"
    if pdf_title_assignment is not None:
        pdf_title_assignment = append_arxiv_id_to_pdf_title(
            pdf_title_assignment,
            arxiv_id,
        )
        updated = replace_pdf_title_assignment(updated, pdf_title_assignment)
        updated = ensure_pdf_metadata_title_at_document_start(
            updated,
            pdf_title_assignment,
        )

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


def ensure_unavailable_latex_date(path: Path) -> bool:
    """Replace or insert a fixed, non-runtime document date."""

    text = path.read_text(encoding="utf-8", errors="ignore")
    spans: list[tuple[int, int]] = []
    for match in DATE_COMMAND_RE.finditer(text):
        index = skip_whitespace(text, match.end())
        if index < len(text) and text[index] == "[":
            optional_end = balanced_group_end(text, index, "[", "]")
            if optional_end is None:
                continue
            index = skip_whitespace(text, optional_end)
        if index >= len(text) or text[index] != "{":
            continue
        end = balanced_group_end(text, index, "{", "}")
        if end is not None:
            spans.append((match.start(), end))

    if spans:
        updated = text
        for start, end in reversed(spans):
            updated = updated[:start] + r"\date{不可用}" + updated[end:]
    else:
        begin_document = BEGIN_DOCUMENT_RE.search(text)
        if begin_document is None:
            return False
        updated = (
            text[: begin_document.start()]
            + r"\date{不可用}"
            + "\n"
            + text[begin_document.start() :]
        )

    if updated == text:
        return False
    path.write_text(updated, encoding="utf-8", newline="")
    return True


def append_arxiv_id_to_pdf_title(title_assignment: str, arxiv_id: str) -> str:
    """Append ``[arXiv:...]`` inside a hyperref ``pdftitle`` assignment."""

    suffix = f"[arXiv:{arxiv_id.strip()}]"
    if not arxiv_id.strip() or suffix.casefold() in title_assignment.casefold():
        return title_assignment

    span = _find_pdf_title_assignment_span(title_assignment)
    if span is None:
        return title_assignment
    return title_assignment[: span[1] - 1] + f" {suffix}" + title_assignment[span[1] - 1 :]


def ensure_pdf_metadata_title_at_document_start(
    text: str,
    title_assignment: str,
) -> str:
    """Set the final PDF title after document-title hooks have run.

    Classes such as ``acmart`` reset PDF metadata while typesetting
    ``\\maketitle``.  Placing this generated setting immediately after that
    command makes the requested title authoritative without changing the
    visible title.  Documents without ``\\maketitle`` use document start.
    """

    snippet = f"{PDF_METADATA_TITLE_MARKER}\n\\hypersetup{{{title_assignment}}}\n"
    updated = text
    marker_start = text.find(PDF_METADATA_TITLE_MARKER)
    if marker_start != -1:
        command_start = text.find(r"\hypersetup", marker_start)
        if command_start == -1:
            return text[:marker_start] + snippet + text[marker_start + len(PDF_METADATA_TITLE_MARKER) :]
        group_start = text.find("{", command_start)
        group_end = (
            balanced_group_end(text, group_start, "{", "}")
            if group_start != -1
            else None
        )
        if group_end is None:
            return text
        updated = text[:marker_start] + text[group_end:]

    begin_document = BEGIN_DOCUMENT_RE.search(updated)
    if begin_document is None:
        return updated
    maketitle = re.search(r"(?<!\\)\\maketitle\b", updated[begin_document.end() :])
    insertion = (
        begin_document.end() + maketitle.end()
        if maketitle is not None
        else begin_document.end()
    )
    return updated[:insertion] + "\n" + snippet + updated[insertion:]


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
    for path in iter_latex_documents(root):
        original = path.read_text(encoding="utf-8", errors="ignore")
        merged = merge_adjacent_citations(original)
        if merged == original:
            continue
        path.write_text(merged, encoding="utf-8", newline="")
        updated.append(path)
    return updated


def remove_empty_caption_paragraphs(text: str) -> str:
    """Replace blank lines in ``\\caption`` arguments with spaces.

    The ``caption`` package rejects paragraph tokens in caption arguments.
    Translation models can introduce blank lines while formatting long captions,
    so normalize only those blank lines and leave regular document paragraphs
    untouched.
    """

    verbatim_spans = _find_verbatim_environment_spans(text)
    output: list[str] = []
    cursor = 0

    for match in re.finditer(r"(?<!\\)\\caption\b", text):
        if _position_in_spans(match.start(), verbatim_spans):
            continue

        argument_start = skip_whitespace(text, match.end())
        if argument_start < len(text) and text[argument_start] == "[":
            optional_end = balanced_group_end(text, argument_start, "[", "]")
            if optional_end is None:
                continue
            argument_start = skip_whitespace(text, optional_end)
        if argument_start >= len(text) or text[argument_start] != "{":
            continue

        argument_end = balanced_group_end(text, argument_start, "{", "}")
        if argument_end is None:
            continue
        caption = text[argument_start + 1 : argument_end - 1]
        normalized_caption = re.sub(r"(?:[ \t]*\r?\n){2,}[ \t]*", " ", caption)
        if normalized_caption == caption:
            continue

        output.append(text[cursor : argument_start + 1])
        output.append(normalized_caption)
        output.append("}")
        cursor = argument_end

    if not output:
        return text
    output.append(text[cursor:])
    return "".join(output)


def remove_empty_caption_paragraphs_in_dir(root: Path) -> list[Path]:
    """Normalize blank caption paragraphs in every TeX document under *root*."""

    updated: list[Path] = []
    for path in iter_latex_documents(root):
        original = path.read_text(encoding="utf-8", errors="ignore")
        normalized = remove_empty_caption_paragraphs(original)
        if normalized == original:
            continue
        path.write_text(normalized, encoding="utf-8", newline="")
        updated.append(path)
    return updated


def _position_in_spans(position: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= position < end for start, end in spans)


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
    for path in iter_source_files(root, LATEX_STYLE_SUFFIXES):
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
        end = balanced_group_end(text, brace_start, "{", "}")
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
    index = skip_whitespace(text, start)
    while index < len(text) and text[index] == "[":
        end = balanced_group_end(text, index, "[", "]")
        if end is None:
            return None
        index = skip_whitespace(text, end)

    if index >= len(text) or text[index] != "{":
        return None
    return balanced_group_end(text, index, "{", "}")


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

        if text.startswith(r"\\", i):
            i += 2
            if i < len(text) and text[i] == "[":
                optional_end = balanced_group_end(text, i, "[", "]")
                if optional_end is not None:
                    i = optional_end
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
        if line[i] == "%" and not is_escaped(line, i):
            if not line[:i].strip():
                return line_ending(line)
            newline = line_ending(line)
            return line[:i].rstrip() + newline
        i += 1
    return line


def _updated_optional_argument_depth(line: str, current_depth: int) -> int:
    depth = current_depth
    if depth == 0 and not LATEX_OPTION_LIST_START_RE.search(line):
        return 0
    for index, char in enumerate(line):
        if is_escaped(line, index):
            continue
        if char == "[":
            depth += 1
        elif char == "]" and depth > 0:
            depth -= 1
    return depth


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
