from __future__ import annotations

import re
from pathlib import Path

from .latex_scan import balanced_group_end, is_escaped, skip_whitespace
from .metadata import ArxivMetadata
from .preferred_translations import append_preferred_translations_section
from .preserved_terms import append_preserved_terms_section
from .source_files import (
    LATEX_DEFINITION_SUFFIXES,
    LATEX_DOCUMENT_SUFFIXES,
    iter_latex_documents,
    iter_source_files,
)
from .tex import strip_latex_comments
from .utils import unique_preserving_order

PREDEFINED_COMMANDS_HEADING = "## Predefined LaTeX Commands"
SECTION_COMMAND_RE = re.compile(
    r"\\(?P<level>part|chapter|section|subsection|subsubsection)\*?\s*\{"
)
PACKAGE_RE = re.compile(r"\\usepackage(?:\[[^\]]*\])?\{([^}]+)\}")
DOCUMENT_CLASS_RE = re.compile(r"\\documentclass(?:\[[^\]]*\])?\{([^}]+)\}")
ENVIRONMENT_RE = re.compile(r"\\begin\{([^}]+)\}")
LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
TITLE_RE = re.compile(
    r"\\(?:title|icmltitle|papertitle|acltitle)(?:\[[^\]]*\])?\s*\{"
)
COMMAND_DEFINITION_RE = re.compile(
    r"\\(?P<kind>"
    r"newcommand|renewcommand|providecommand|DeclareRobustCommand|"
    r"DeclareMathOperator|def|gdef|edef|xdef|let"
    r")\*?(?![A-Za-z@])"
)
MATH_ENVIRONMENT_BEGIN_RE = re.compile(
    r"\\begin\{(?P<name>equation|align|gather|multline|split|cases)(?P<star>\*)?\}"
)


def generate_template_paper_guide(
    source_dir: Path,
    guide_path: Path,
    metadata: ArxivMetadata | None = None,
) -> str:
    """Generate a deterministic translation guide without an API request."""

    source_texts = _collect_source_texts(source_dir)
    predefined_commands = collect_predefined_latex_commands(source_dir)
    guide = _render_template_guide(source_dir, source_texts, metadata)
    guide = append_predefined_commands_section(guide, predefined_commands)
    guide = append_preferred_translations_section(guide)
    guide = append_preserved_terms_section(guide)
    guide_path.parent.mkdir(parents=True, exist_ok=True)
    guide_path.write_text(guide, encoding="utf-8", newline="\n")
    return guide


def _collect_source_texts(source_dir: Path) -> dict[Path, str]:
    texts: dict[Path, str] = {}
    for path in iter_latex_documents(source_dir):
        texts[path] = strip_latex_comments(
            path.read_text(encoding="utf-8", errors="ignore")
        )
    return texts


def _render_template_guide(
    source_dir: Path,
    source_texts: dict[Path, str],
    metadata: ArxivMetadata | None,
) -> str:
    combined = "\n".join(source_texts.values())
    source_title = _extract_first_braced_argument(combined, TITLE_RE)
    title = (metadata.title if metadata and metadata.title else source_title) or ""
    sections = _extract_sections(source_texts)
    packages = _unique_sorted(
        package.strip()
        for match in PACKAGE_RE.finditer(combined)
        for package in match.group(1).split(",")
        if package.strip()
    )
    document_classes = _unique_sorted(
        match.group(1).strip()
        for match in DOCUMENT_CLASS_RE.finditer(combined)
        if match.group(1).strip()
    )
    environments = _unique_sorted(
        match.group(1).strip()
        for match in ENVIRONMENT_RE.finditer(combined)
        if match.group(1).strip()
    )
    labels = _unique_sorted(match.group(1).strip() for match in LABEL_RE.finditer(combined))
    files = [
        path.relative_to(source_dir).as_posix()
        for path in sorted(source_texts)
    ]

    structure = "\n".join(
        f"- `{level}`: `{_escape_markdown_code(heading)}`"
        for level, heading in sections
    ) or "- No explicit section commands were detected."
    package_list = _inline_code_list(packages) or "None detected."
    class_list = _inline_code_list(document_classes) or "None detected."
    environment_list = _inline_code_list(environments) or "None detected."
    file_list = "\n".join(f"- `{path}`" for path in files)
    if not file_list:
        file_list = "- No `.tex` or `.ltx` files were detected."

    cautions = [
        "- Preserve every LaTeX command, environment name, argument boundary, label, "
        "citation key, file path, URL, and math expression exactly.",
        "- Translate visible prose in headings, captions, theorem statements, table "
        "cells, and list items while preserving their surrounding LaTeX structure.",
        "- Keep the complete `\\title` command and PDF title metadata in English.",
        "- Do not translate bibliography entries, code, verbatim-like environments, "
        "package options, graphics paths, or input/include targets.",
    ]
    if any(env in environments for env in ("table", "table*", "tabular", "tabularx")):
        cautions.append(
            "- Tables are present: preserve `&`, `\\\\`, row counts, column specs, "
            "`\\multicolumn`, and `\\multirow` structure."
        )
    if any(env in environments for env in ("figure", "figure*", "subfigure")):
        cautions.append(
            "- Figures are present: translate caption prose only; preserve graphics "
            "paths, labels, placement options, and sizing commands."
        )
    if any(
        env in environments
        for env in ("algorithm", "algorithmic", "lstlisting", "minted", "verbatim")
    ):
        cautions.append(
            "- Algorithms or code-like blocks are present: preserve code, identifiers, "
            "keywords, indentation, and line structure."
        )
    if labels:
        cautions.append(
            f"- Cross-references are present ({len(labels)} labels detected): never "
            "translate label or reference identifiers."
        )

    metadata_sections = _render_arxiv_metadata_sections(metadata)
    title_item = (
        f"- Original title: `{_escape_markdown_code(title)}`\n"
        if title
        else ""
    )

    return (
        "# Paper Translation Guide\n\n"
        "This guide is generated locally from the LaTeX source and available arXiv "
        "metadata. It does not infer unstated claims or send the complete paper to an "
        "external model.\n\n"
        f"{metadata_sections}"
        "## Structure\n"
        f"{structure}\n\n"
        "## Glossary\n"
        "| English term | Chinese translation | Notes |\n"
        "| --- | --- | --- |\n"
        "| See Preferred Fixed Translations below | Use the configured translation | "
        "Apply consistently throughout the paper |\n"
        "| Unlisted specialized term | Context-dependent | Keep English when uncertain |\n\n"
        "## Proper Nouns And Keep-English Items\n"
        f"{title_item}"
        f"- Document class(es): {class_list}\n"
        f"- Packages detected: {package_list}\n"
        f"- Environment names detected: {environment_list}\n"
        "- Preserve model names, dataset names, software, people, institutions, "
        "mathematical symbols, citation keys, labels, URLs, and code identifiers.\n"
        "- Source files:\n"
        f"{file_list}\n\n"
        "## Style Rules\n"
        "- Use concise, formal, natural Simplified Chinese suitable for an academic paper.\n"
        "- Keep terminology consistent across chunks and follow the fixed translation "
        "and keep-English sections below.\n"
        "- Preserve mathematical notation and do not simplify, reinterpret, add, remove, "
        "or reorder technical claims.\n"
        "- Translate all visible English prose unless it is code, metadata, a proper noun, "
        "or an item explicitly marked to remain in English.\n\n"
        "## LaTeX Cautions\n"
        + "\n".join(cautions)
        + "\n"
    )


def _render_arxiv_metadata_sections(metadata: ArxivMetadata | None) -> str:
    if metadata is None:
        return ""

    sections: list[str] = []
    categories = unique_preserving_order(
        [
            category
            for category in [metadata.primary_category, *metadata.categories]
            if category
        ]
    )
    if categories:
        field_lines = ["## Field And Subfield"]
        if metadata.primary_category:
            field_lines.append(
                f"- arXiv primary category: `{metadata.primary_category}`"
            )
        field_lines.append(
            "- arXiv categories: "
            + ", ".join(f"`{category}`" for category in categories)
        )
        sections.append("\n".join(field_lines))

    topic_lines: list[str] = []
    if metadata.title:
        topic_lines.append(
            f"- Title: `{_escape_markdown_code(metadata.title)}`"
        )
    if metadata.abstract:
        topic_lines.append(f"- Abstract: {metadata.abstract}")
    if topic_lines:
        sections.append("## Topic Context From arXiv\n" + "\n".join(topic_lines))

    if not sections:
        return ""
    return "\n\n".join(sections) + "\n\n"


def _extract_sections(
    source_texts: dict[Path, str],
) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    for text in source_texts.values():
        for match in SECTION_COMMAND_RE.finditer(text):
            brace_start = match.end() - 1
            brace_end = balanced_group_end(text, brace_start, "{", "}")
            if brace_end is None:
                continue
            heading = re.sub(
                r"\s+",
                " ",
                text[brace_start + 1 : brace_end - 1],
            ).strip()
            if heading:
                sections.append((match.group("level"), heading))
    return sections


def _extract_first_braced_argument(
    text: str,
    pattern: re.Pattern[str],
) -> str | None:
    match = pattern.search(text)
    if match is None:
        return None
    brace_start = match.end() - 1
    brace_end = balanced_group_end(text, brace_start, "{", "}")
    if brace_end is None:
        return None
    return re.sub(r"\s+", " ", text[brace_start + 1 : brace_end - 1]).strip()


def _collect_math_contexts(text: str) -> list[str]:
    """Collect math spans using bounded scans instead of backtracking regexes."""

    contexts: list[str] = []
    position = 0
    while position < len(text):
        if text.startswith(r"\(", position):
            end = text.find(r"\)", position + 2)
            if end >= 0:
                contexts.append(text[position : end + 2])
                position = end + 2
                continue
        if text.startswith(r"\[", position):
            end = text.find(r"\]", position + 2)
            if end >= 0:
                contexts.append(text[position : end + 2])
                position = end + 2
                continue
        if text.startswith("$$", position) and not is_escaped(text, position):
            end = _find_unescaped_token(text, "$$", position + 2)
            if end >= 0:
                contexts.append(text[position : end + 2])
                position = end + 2
                continue
        if (
            text[position] == "$"
            and not is_escaped(text, position)
            and not text.startswith("$$", position)
        ):
            end = _find_unescaped_single_dollar(text, position + 1)
            if end >= 0:
                contexts.append(text[position : end + 1])
                position = end + 1
                continue
        position += 1

    for match in MATH_ENVIRONMENT_BEGIN_RE.finditer(text):
        name = match.group("name") + (match.group("star") or "")
        closing = rf"\end{{{name}}}"
        end = text.find(closing, match.end())
        if end >= 0:
            contexts.append(text[match.start() : end + len(closing)])
    return contexts


def _find_unescaped_token(text: str, token: str, start: int) -> int:
    position = text.find(token, start)
    while position >= 0:
        if not is_escaped(text, position):
            return position
        position = text.find(token, position + len(token))
    return -1


def _find_unescaped_single_dollar(text: str, start: int) -> int:
    position = text.find("$", start)
    while position >= 0:
        if (
            not is_escaped(text, position)
            and not text.startswith("$$", position)
            and (position == 0 or text[position - 1] != "$")
        ):
            return position
        position = text.find("$", position + 1)
    return -1


def _unique_sorted(values) -> list[str]:
    return sorted(set(values), key=str.casefold)


def _inline_code_list(values: list[str]) -> str:
    return ", ".join(f"`{_escape_markdown_code(value)}`" for value in values)


def collect_predefined_latex_commands(source_dir: Path) -> tuple[str, ...]:
    """Collect user-facing custom command definitions from the paper source."""

    source_files = list(iter_source_files(source_dir, LATEX_DEFINITION_SUFFIXES))
    texts = {
        path: strip_latex_comments(
            path.read_text(encoding="utf-8", errors="ignore")
        )
        for path in source_files
    }
    document_math_text = "\n".join(
        "\n".join(_collect_math_contexts(text))
        for path, text in texts.items()
        if path.suffix.lower() in LATEX_DOCUMENT_SUFFIXES
    )

    commands: list[str] = []
    seen: set[str] = set()
    for path, text in texts.items():
        for name, definition in _extract_command_definitions(text):
            if (
                path.suffix.lower() not in LATEX_DOCUMENT_SUFFIXES
                and not re.search(
                    rf"\\{re.escape(name)}(?![A-Za-z@])",
                    document_math_text,
                )
            ):
                continue
            normalized = re.sub(r"\s+", " ", definition).strip()
            if normalized in seen:
                continue
            seen.add(normalized)
            commands.append(normalized)
    return tuple(commands)


def append_predefined_commands_section(
    guide: str,
    commands: tuple[str, ...],
) -> str:
    """Add or refresh the deterministic custom-command section in a paper guide."""

    section_pattern = re.compile(
        rf"(?ms)^{re.escape(PREDEFINED_COMMANDS_HEADING)}\n.*?(?=^## |\Z)"
    )
    guide_without_section = section_pattern.sub("", guide).rstrip()
    if not commands:
        return guide_without_section

    definitions = "\n".join(f"- `{_escape_markdown_code(command)}`" for command in commands)
    section = (
        f"{PREDEFINED_COMMANDS_HEADING}\n"
        "These definitions are source context for translation. Preserve every macro "
        "invocation and its arguments exactly. Preserve explicit LaTeX control spaces. "
        "When a zero-argument macro directly touches Chinese or other non-ASCII prose, "
        "terminate the macro name with an empty group (`{}`) so the following text "
        "cannot be parsed as part of a control sequence.\n"
        f"{definitions}\n"
    )
    return f"{guide_without_section}\n\n{section}"


def _extract_command_definitions(text: str) -> list[tuple[str, str]]:
    definitions: list[tuple[str, str]] = []
    for match in COMMAND_DEFINITION_RE.finditer(text):
        parsed = _parse_command_definition(text, match)
        if parsed is not None:
            definitions.append(parsed)
    return definitions


def _parse_command_definition(
    text: str,
    match: re.Match[str],
) -> tuple[str, str] | None:
    kind = match.group("kind")
    position = skip_whitespace(text, match.end())
    if kind == "let":
        name_match = re.match(r"\\([A-Za-z@]+)", text[position:])
        if name_match is None or "@" in name_match.group(1):
            return None
        line_end = text.find("\n", position)
        end = len(text) if line_end < 0 else line_end
        return name_match.group(1), text[match.start() : end].strip()

    if kind in {"def", "gdef", "edef", "xdef"}:
        name_match = re.match(r"\\([A-Za-z@]+)", text[position:])
        if name_match is None or "@" in name_match.group(1):
            return None
        name = name_match.group(1)
        body_start = text.find("{", position + name_match.end())
        if body_start < 0:
            return None
        body_end = balanced_group_end(text, body_start, "{", "}")
        if body_end is None:
            return None
        return name, text[match.start() : body_end]

    name, position = _parse_declared_command_name(text, position)
    if name is None or "@" in name:
        return None
    position = skip_whitespace(text, position)
    while position < len(text) and text[position] == "[":
        optional_end = balanced_group_end(text, position, "[", "]")
        if optional_end is None:
            return None
        position = skip_whitespace(text, optional_end)
    if position >= len(text) or text[position] != "{":
        return None
    body_end = balanced_group_end(text, position, "{", "}")
    if body_end is None:
        return None
    return name, text[match.start() : body_end]


def _parse_declared_command_name(
    text: str,
    position: int,
) -> tuple[str | None, int]:
    if position >= len(text):
        return None, position
    if text[position] == "{":
        group_end = balanced_group_end(text, position, "{", "}")
        if group_end is None:
            return None, position
        group = text[position + 1 : group_end - 1].strip()
        name_match = re.fullmatch(r"\\([A-Za-z@]+)", group)
        if name_match is None:
            return None, position
        return name_match.group(1), group_end

    name_match = re.match(r"\\([A-Za-z@]+)", text[position:])
    if name_match is None:
        return None, position
    return name_match.group(1), position + name_match.end()


def _escape_markdown_code(text: str) -> str:
    return text.replace("`", "\\`")
