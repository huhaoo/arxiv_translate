from __future__ import annotations

import re
from pathlib import Path

DOCUMENTCLASS_RE = re.compile(r"\\documentclass(?:\[[^\]]*\])?\{[^}]+\}")
PDFOUTPUT_RE = re.compile(r"(?m)^(?P<indent>\s*)\\pdfoutput\s*=\s*(?P<value>\d+)\s*$")
BBM_PACKAGE_RE = re.compile(
    r"(?m)^(?P<indent>\s*)\\usepackage(?P<options>\[[^\]]*\])?\{bbm\}(?P<tail>\s*(?:%.*)?)$"
)
PDFTEX_GUARDED_PDFOUTPUT_RE = re.compile(
    r"\\ifPDFTeX\s*\\pdfoutput\s*=\s*\d+\s*\\fi",
    re.DOTALL,
)
DECLARE_UNICODE_CHARACTER_RE = re.compile(r"^\s*\\DeclareUnicodeCharacter\b")


def ensure_chinese_latex_support(main_tex: Path) -> bool:
    """Inject ctex support into the main TeX file if no CJK package is present."""

    text = main_tex.read_text(encoding="utf-8", errors="ignore")
    original = text
    text = guard_pdftex_compatibility_for_xelatex(text)
    lowered = text.lower()
    has_cjk_support = (
        "\\usepackage{ctex}" in lowered
        or "\\usepackage[utf8]{ctex}" in lowered
        or "\\usepackage{xecjk}" in lowered
        or "\\usepackage{cjk}" in lowered
    )
    if not has_cjk_support:
        match = DOCUMENTCLASS_RE.search(text)
        if match:
            injection = (
                "\n"
                "% Added by arxiv-translate for Chinese output.\n"
                "\\usepackage{iftex}\n"
                "\\ifPDFTeX\n"
                "  \\usepackage[UTF8]{ctex}\n"
                "\\else\n"
                "  \\usepackage{ctex}\n"
                "\\fi\n"
            )
            text = text[: match.end()] + injection + text[match.end() :]

    if "\\ifPDFTeX" in text and not _has_iftex_package(text):
        text = _insert_after_documentclass(text, "\\usepackage{iftex}\n")

    if text == original:
        return False
    main_tex.write_text(text, encoding="utf-8", newline="")
    return True


def ensure_latex_compatibility(root: Path) -> list[Path]:
    """Apply XeLaTeX compatibility fixes to every TeX file in a source tree."""

    tex_files = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".tex", ".ltx"}
    ]
    tree_texts = [
        path.read_text(encoding="utf-8", errors="ignore") for path in tex_files
    ]
    uses_double_stroke_fix = any(
        BBM_PACKAGE_RE.search(text) or "\\usepackage{dsfont}" in text
        for text in tree_texts
    )
    changed: list[Path] = []
    for path, text in zip(tex_files, tree_texts):
        fixed = guard_pdftex_compatibility_for_xelatex(text)
        if uses_double_stroke_fix:
            fixed = replace_bbm_with_dsfont_for_xelatex(fixed, replace_macros=True)
        if fixed != text:
            path.write_text(fixed, encoding="utf-8", newline="")
            changed.append(path)
    return changed


def guard_pdftex_compatibility_for_xelatex(text: str) -> str:
    """Guard common pdfTeX-only preamble commands before XeLaTeX compilation."""

    text = guard_pdfoutput_for_xelatex(text)
    text = guard_declare_unicode_character_for_xelatex(text)
    return replace_bbm_with_dsfont_for_xelatex(text)


def guard_pdfoutput_for_xelatex(text: str) -> str:
    """Wrap bare pdfTeX-only \\pdfoutput assignments so XeLaTeX can compile."""

    if "\\pdfoutput" not in text:
        return text

    def replace(match: re.Match[str]) -> str:
        start = max(0, match.start() - 40)
        end = min(len(text), match.end() + 40)
        nearby = text[start:end]
        if PDFTEX_GUARDED_PDFOUTPUT_RE.search(nearby):
            return match.group(0)
        indent = match.group("indent")
        value = match.group("value")
        return f"{indent}\\ifPDFTeX\n{indent}\\pdfoutput={value}\n{indent}\\fi"

    return PDFOUTPUT_RE.sub(replace, text)


def guard_declare_unicode_character_for_xelatex(text: str) -> str:
    """Wrap bare \\DeclareUnicodeCharacter lines for XeLaTeX compatibility."""

    if "\\DeclareUnicodeCharacter" not in text:
        return text

    output: list[str] = []
    pdftex_depth = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        inside_pdftex = pdftex_depth > 0
        if stripped == r"\ifPDFTeX":
            pdftex_depth += 1

        if DECLARE_UNICODE_CHARACTER_RE.match(line) and not inside_pdftex:
            indent = line[: len(line) - len(line.lstrip())]
            newline = "\n" if line.endswith("\n") else ""
            body = line[:-1] if newline else line
            output.append(f"{indent}\\ifPDFTeX\n")
            output.append(f"{body}\n")
            output.append(f"{indent}\\fi{newline}")
        else:
            output.append(line)

        if stripped == r"\fi" and pdftex_depth > 0:
            pdftex_depth -= 1

    return "".join(output)


def replace_bbm_with_dsfont_for_xelatex(
    text: str,
    *,
    replace_macros: bool = False,
) -> str:
    """Use Type1 double-stroke fonts instead of bitmap-only bbm fonts."""

    has_bbm_package = BBM_PACKAGE_RE.search(text) is not None
    if not has_bbm_package and not replace_macros:
        return text

    def replace_package(match: re.Match[str]) -> str:
        return f"{match.group('indent')}\\usepackage{{dsfont}}{match.group('tail')}"

    if has_bbm_package:
        text = BBM_PACKAGE_RE.sub(replace_package, text)
    if has_bbm_package or replace_macros:
        text = text.replace(r"\mathbbm", r"\mathds")
    return text


def _has_iftex_package(text: str) -> bool:
    lowered = text.lower()
    return "\\usepackage{iftex}" in lowered or "\\usepackage[iftex]" in lowered


def _insert_after_documentclass(text: str, insertion: str) -> str:
    match = DOCUMENTCLASS_RE.search(text)
    if not match:
        return text
    return text[: match.end()] + "\n" + insertion + text[match.end() :]
