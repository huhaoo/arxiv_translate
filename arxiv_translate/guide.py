from __future__ import annotations

import re
from pathlib import Path

from .deepseek import DeepSeekClient, DeepSeekFailoverClient
from .preferred_translations import append_preferred_translations_section
from .preserved_terms import append_preserved_terms_section
from .tex import strip_latex_comments

LATEX_DOCUMENT_SUFFIXES = {".tex", ".ltx"}
LATEX_DEFINITION_SUFFIXES = LATEX_DOCUMENT_SUFFIXES | {".sty", ".cls"}
PREDEFINED_COMMANDS_HEADING = "## Predefined LaTeX Commands"
COMMAND_DEFINITION_RE = re.compile(
    r"\\(?P<kind>"
    r"newcommand|renewcommand|providecommand|DeclareRobustCommand|"
    r"DeclareMathOperator|def|gdef|edef|xdef|let"
    r")\*?(?![A-Za-z@])"
)
MATH_CONTEXT_RE = re.compile(
    r"(?<!\\)\$\$(?:\\.|.)*?(?<!\\)\$\$"
    r"|(?<![\\$])\$(?!\$)(?:\\.|[^$])+(?<!\\)\$(?!\$)"
    r"|\\\((?:\\.|.)*?\\\)"
    r"|\\\[(?:\\.|.)*?\\\]"
    r"|\\begin\{(?:equation|align|gather|multline|split|cases)\*?\}"
    r".*?"
    r"\\end\{(?:equation|align|gather|multline|split|cases)\*?\}",
    re.DOTALL,
)


def load_or_generate_paper_guide(
    source_dir: Path,
    guide_path: Path,
    client: DeepSeekClient | DeepSeekFailoverClient,
) -> str:
    predefined_commands = collect_predefined_latex_commands(source_dir)
    if guide_path.exists():
        guide = guide_path.read_text(encoding="utf-8")
        guide = append_predefined_commands_section(guide, predefined_commands)
        guide = append_preferred_translations_section(guide)
        guide = append_preserved_terms_section(guide)
        guide_path.write_text(guide, encoding="utf-8", newline="\n")
        return guide

    latex_document = collect_latex_document(source_dir)
    guide = client.generate_paper_guide(latex_document)
    guide = append_predefined_commands_section(guide, predefined_commands)
    guide = append_preferred_translations_section(guide)
    guide = append_preserved_terms_section(guide)
    guide_path.parent.mkdir(parents=True, exist_ok=True)
    guide_path.write_text(guide, encoding="utf-8", newline="\n")
    return guide


def collect_latex_document(source_dir: Path) -> str:
    parts: list[str] = []
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in LATEX_DOCUMENT_SUFFIXES:
            continue
        relative = path.relative_to(source_dir).as_posix()
        text = strip_latex_comments(path.read_text(encoding="utf-8", errors="ignore"))
        parts.append(f"<LATEX_FILE path=\"{relative}\">\n{text}\n</LATEX_FILE>")
    return "\n\n".join(parts)


def collect_predefined_latex_commands(source_dir: Path) -> tuple[str, ...]:
    """Collect user-facing custom command definitions from the paper source."""

    source_files = [
        path
        for path in sorted(source_dir.rglob("*"))
        if path.is_file() and path.suffix.lower() in LATEX_DEFINITION_SUFFIXES
    ]
    texts = {
        path: strip_latex_comments(
            path.read_text(encoding="utf-8", errors="ignore")
        )
        for path in source_files
    }
    document_math_text = "\n".join(
        "\n".join(MATH_CONTEXT_RE.findall(text))
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
    position = _skip_whitespace(text, match.end())
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
        body_end = _balanced_group_end(text, body_start, "{", "}")
        if body_end is None:
            return None
        return name, text[match.start() : body_end]

    name, position = _parse_declared_command_name(text, position)
    if name is None or "@" in name:
        return None
    position = _skip_whitespace(text, position)
    while position < len(text) and text[position] == "[":
        optional_end = _balanced_group_end(text, position, "[", "]")
        if optional_end is None:
            return None
        position = _skip_whitespace(text, optional_end)
    if position >= len(text) or text[position] != "{":
        return None
    body_end = _balanced_group_end(text, position, "{", "}")
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
        group_end = _balanced_group_end(text, position, "{", "}")
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


def _balanced_group_end(
    text: str,
    start: int,
    opening: str,
    closing: str,
) -> int | None:
    depth = 0
    for position in range(start, len(text)):
        character = text[position]
        if _is_escaped(text, position):
            continue
        if character == opening:
            depth += 1
        elif character == closing:
            depth -= 1
            if depth == 0:
                return position + 1
    return None


def _is_escaped(text: str, position: int) -> bool:
    backslashes = 0
    position -= 1
    while position >= 0 and text[position] == "\\":
        backslashes += 1
        position -= 1
    return backslashes % 2 == 1


def _skip_whitespace(text: str, position: int) -> int:
    while position < len(text) and text[position].isspace():
        position += 1
    return position


def _escape_markdown_code(text: str) -> str:
    return text.replace("`", "\\`")
