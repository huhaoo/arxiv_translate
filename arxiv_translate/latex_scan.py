from __future__ import annotations


def is_escaped(text: str, position: int) -> bool:
    """Return whether the character at *position* follows an odd slash run."""

    backslashes = 0
    position -= 1
    while position >= 0 and text[position] == "\\":
        backslashes += 1
        position -= 1
    return backslashes % 2 == 1


def visible_latex_line(line: str) -> str:
    """Return the part of a LaTeX line before its first real comment."""

    for position, character in enumerate(line):
        if character == "%" and not is_escaped(line, position):
            return line[:position]
    return line


def balanced_group_end(
    text: str,
    start: int,
    opening: str,
    closing: str,
) -> int | None:
    """Return the position after a balanced group, ignoring escaped delimiters."""

    depth = 0
    for position in range(start, len(text)):
        if is_escaped(text, position):
            continue
        character = text[position]
        if character == opening:
            depth += 1
        elif character == closing:
            depth -= 1
            if depth == 0:
                return position + 1
    return None


def skip_whitespace(text: str, position: int) -> int:
    while position < len(text) and text[position].isspace():
        position += 1
    return position


def line_ending(line: str) -> str:
    for ending in ("\r\n", "\n", "\r"):
        if line.endswith(ending):
            return ending
    return ""


def contains_unescaped(text: str, target: str) -> bool:
    return any(
        character == target and not is_escaped(text, position)
        for position, character in enumerate(text)
    )
