from __future__ import annotations

import re
from pathlib import Path

DOCUMENTCLASS_RE = re.compile(r"\\documentclass(?:\[[^\]]*\])?\{[^}]+\}")
PDFOUTPUT_RE = re.compile(r"(?m)^(?P<indent>\s*)\\pdfoutput\s*=\s*(?P<value>\d+)\s*$")
BBM_PACKAGE_RE = re.compile(
    r"(?m)^(?P<indent>\s*)\\usepackage(?P<options>\[[^\]]*\])?\{bbm\}(?P<tail>\s*(?:%.*)?)$"
)
MICROTYPE_PACKAGE_RE = re.compile(
    r"^\s*(?:\\AtEndOfClass\{)?\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{microtype\}"
)
CJKUTF8_PACKAGE_RE = re.compile(
    r"(?m)^(?P<indent>\s*)\\usepackage(?P<options>\[[^\]]*\])?\{CJKutf8\}(?P<tail>\s*(?:%.*)?)$"
)
PDFTEX_GUARDED_PDFOUTPUT_RE = re.compile(
    r"\\ifPDFTeX\s*\\pdfoutput\s*=\s*\d+\s*\\fi",
    re.DOTALL,
)
CJK_ENVIRONMENT_SHIM = (
    "\\ifPDFTeX\n"
    "\\usepackage{CJKutf8}\n"
    "\\else\n"
    "\\newenvironment{CJK}[3]{}{}\n"
    "\\fi"
)
DECLARE_UNICODE_CHARACTER_RE = re.compile(r"^\s*\\DeclareUnicodeCharacter\b")
LATEX_COMPAT_SUFFIXES = {".tex", ".ltx", ".sty", ".cls"}


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
                "  \\usepackage[fontset=fandol]{ctex}\n"
                "\\fi\n"
            )
            text = text[: match.end()] + injection + text[match.end() :]

    text = prefer_fandol_ctex_for_xelatex(text)

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
        if path.is_file() and path.suffix.lower() in LATEX_COMPAT_SUFFIXES
    ]
    tree_texts = [
        path.read_text(encoding="utf-8", errors="ignore") for path in tex_files
    ]
    uses_double_stroke_fix = any(
        BBM_PACKAGE_RE.search(text) or "\\usepackage{dsfont}" in text
        for text in tree_texts
    )
    zero_arg_macro_names = set().union(*(_zero_arg_macro_names(text) for text in tree_texts))
    changed: list[Path] = []
    for path, text in zip(tex_files, tree_texts):
        fixed = guard_pdftex_compatibility_for_xelatex(
            text,
            zero_arg_macro_names=zero_arg_macro_names,
        )
        if uses_double_stroke_fix:
            fixed = replace_bbm_with_dsfont_for_xelatex(fixed, replace_macros=True)
        if fixed != text:
            path.write_text(fixed, encoding="utf-8", newline="")
            changed.append(path)
    return changed


def guard_pdftex_compatibility_for_xelatex(
    text: str,
    *,
    zero_arg_macro_names: set[str] | None = None,
) -> str:
    """Guard common pdfTeX-only preamble commands before XeLaTeX compilation."""

    text = escape_unescaped_numeric_percentages(text)
    text = remove_blank_lines_in_multiline_usepackage_options(text)
    text = downgrade_unaligned_align_environments(text)
    text = remove_blank_lines_in_math_environments(text)
    text = replace_px_units_with_pt(text)
    text = close_unclosed_preamble_single_line_commands(text)
    text = protect_zero_arg_macros_before_nonascii(text, zero_arg_macro_names)
    text = prefer_numeric_natbib_for_numeric_bibliography_styles(text)
    text = prefer_fandol_ctex_for_xelatex(text)
    text = guard_pdfoutput_for_xelatex(text)
    text = guard_declare_unicode_character_for_xelatex(text)
    text = guard_microtype_for_xelatex(text)
    text = guard_cjkutf8_for_xelatex(text)
    text = replace_bbm_with_dsfont_for_xelatex(text)
    return ensure_iftex_loaded_before_ifpdftex(text)


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

    return _guard_lines_for_pdftex(text, DECLARE_UNICODE_CHARACTER_RE)


def guard_microtype_for_xelatex(text: str) -> str:
    """Load microtype only under pdfTeX to avoid XeTeX font patch failures."""

    if "\\usepackage{microtype}" not in text and "{microtype}" not in text:
        return text

    return _guard_lines_for_pdftex(text, MICROTYPE_PACKAGE_RE)


def guard_cjkutf8_for_xelatex(text: str) -> str:
    """Keep legacy CJK environments usable when compiling with XeLaTeX."""

    if "CJKutf8" not in text and r"\begin{CJK}" not in text:
        return text
    if r"\newenvironment{CJK}" in text:
        return text

    if CJKUTF8_PACKAGE_RE.search(text):
        return CJKUTF8_PACKAGE_RE.sub(_replace_cjkutf8_package, text, count=1)

    return _insert_after_documentclass(text, CJK_ENVIRONMENT_SHIM + "\n")


def _replace_cjkutf8_package(match: re.Match[str]) -> str:
    indent = match.group("indent")
    tail = match.group("tail")
    shim = "\n".join(f"{indent}{line}" for line in CJK_ENVIRONMENT_SHIM.splitlines())
    return f"{shim}{tail}"


def remove_blank_lines_in_multiline_usepackage_options(text: str) -> str:
    """Remove blank paragraphs inside multi-line \\usepackage option lists."""

    output: list[str] = []
    inside_usepackage_options = False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if inside_usepackage_options and not stripped:
            continue
        output.append(line)
        if not inside_usepackage_options and re.match(r"^\s*\\usepackage\s*\[\s*$", line):
            inside_usepackage_options = True
            continue
        if inside_usepackage_options and re.match(r"^\s*\]\s*\{[^}]+\}", line):
            inside_usepackage_options = False
    return "".join(output)


def downgrade_unaligned_align_environments(text: str) -> str:
    """Use equation for align environments that have no alignment points."""

    def replace(match: re.Match[str]) -> str:
        environment = match.group(1)
        body = match.group(2)
        if _has_unescaped_ampersand(body):
            return match.group(0)
        replacement = "equation*" if environment.endswith("*") else "equation"
        return f"\\begin{{{replacement}}}{body}\\end{{{replacement}}}"

    return re.sub(r"\\begin\{(align\*?)\}(.*?)\\end\{\1\}", replace, text, flags=re.DOTALL)


def remove_blank_lines_in_math_environments(text: str) -> str:
    """Remove paragraph breaks inside display math environments."""

    environments = "|".join(
        [
            "align\\*?",
            "equation\\*?",
            "gather\\*?",
            "multline\\*?",
            "split",
        ]
    )

    def replace(match: re.Match[str]) -> str:
        environment = match.group(1)
        body = match.group(2)
        lines = [line for line in body.splitlines(keepends=True) if line.strip()]
        return f"\\begin{{{environment}}}{''.join(lines)}\\end{{{environment}}}"

    return re.sub(
        rf"\\begin\{{({environments})\}}(.*?)\\end\{{\1\}}",
        replace,
        text,
        flags=re.DOTALL,
    )


def replace_px_units_with_pt(text: str) -> str:
    """Replace CSS-style px length units with TeX-supported pt units."""

    return re.sub(r"(?P<number>-?\d+(?:\.\d+)?)\s*px\b", r"\g<number>pt", text)


def escape_unescaped_numeric_percentages(text: str) -> str:
    """Escape bare percent signs in numeric percentages accidentally emitted by translation."""

    return re.sub(r"(?<!\\)(\d)\s*%(?=[ \t]*(?:\S|\r?\n|$))", r"\1\\%", text)


def close_unclosed_preamble_single_line_commands(text: str) -> str:
    """Close short preamble commands that translation accidentally left open."""

    lines = text.splitlines(keepends=True)
    output: list[str] = []
    for index, line in enumerate(lines):
        fixed = line
        if re.match(r"^\s*\\(?:title|date)\{", line):
            missing = _missing_closing_braces(line)
            if missing > 0 and _next_nonblank_is_preamble_boundary(lines, index + 1):
                ending = _line_ending(line)
                body = line[: -len(ending)] if ending else line
                fixed = body.rstrip() + ("}" * missing) + ending
        output.append(fixed)
    return "".join(output)


def protect_zero_arg_macros_before_nonascii(
    text: str,
    macro_names: set[str] | None = None,
) -> str:
    """Add an empty group after no-argument macros before CJK/non-ASCII text."""

    names = set(macro_names or set())
    names.update(_zero_arg_macro_names(text))
    if not names:
        return text

    pattern = re.compile(rf"\\({'|'.join(re.escape(name) for name in sorted(names, key=len, reverse=True))})(?=[^\x00-\x7F])")
    output: list[str] = []
    for line in text.splitlines(keepends=True):
        if _is_macro_definition_line(line):
            output.append(line)
        else:
            output.append(pattern.sub(r"\\\1{}", line))
    return "".join(output)


def prefer_numeric_natbib_for_numeric_bibliography_styles(text: str) -> str:
    """Use numeric natbib mode with numeric bibliography styles."""

    if not re.search(r"\\bibliographystyle\{(?:plain|unsrt|abbrv|ieeetr|IEEEtran)\}", text):
        return text
    return re.sub(
        r"(?m)^(?P<indent>\s*)\\usepackage\{natbib\}(?P<tail>\s*(?:%.*)?)$",
        r"\g<indent>\\usepackage[numbers]{natbib}\g<tail>",
        text,
        count=1,
    )


def prefer_fandol_ctex_for_xelatex(text: str) -> str:
    """Avoid system SimSun dependency by using TeX Live's Fandol CJK fonts."""

    return re.sub(
        r"(?m)^(?P<indent>\s*)\\usepackage\{ctex\}(?P<tail>\s*(?:%.*)?)$",
        r"\g<indent>\\usepackage[fontset=fandol]{ctex}\g<tail>",
        text,
    )


def _zero_arg_macro_names(text: str) -> set[str]:
    names = set(re.findall(r"\\(?:newcommand|renewcommand)\{\\([A-Za-z]+)\}\{", text))
    names.update(re.findall(r"\\def\\([A-Za-z]+)\{", text))
    return names


def _is_macro_definition_line(line: str) -> bool:
    return bool(re.search(r"\\(?:newcommand|renewcommand)\{\\[A-Za-z]+\}|\\def\\[A-Za-z]+", line))


def _missing_closing_braces(line: str) -> int:
    depth = 0
    escaped = False
    for char in line:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
    return depth


def _next_nonblank_is_preamble_boundary(lines: list[str], start: int) -> bool:
    for line in lines[start:]:
        stripped = line.strip()
        if not stripped:
            continue
        return bool(
            re.match(
                r"^\\(?:author|begin\{abstract\}|begin\{document\}|maketitle|section|usepackage)",
                stripped,
            )
        )
    return False


def _line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    if line.endswith("\r"):
        return "\r"
    return ""


def ensure_iftex_loaded_before_ifpdftex(text: str) -> str:
    """Define \\ifPDFTeX before any guarded pdfTeX-only commands use it."""

    first_ifpdftex = text.find(r"\ifPDFTeX")
    if first_ifpdftex == -1:
        return text

    first_iftex_load = _first_iftex_load_index(text)
    if first_iftex_load != -1 and first_iftex_load < first_ifpdftex:
        return text

    return text[:first_ifpdftex] + "\\RequirePackage{iftex}\n" + text[first_ifpdftex:]


def _first_iftex_load_index(text: str) -> int:
    matches = [
        index
        for needle in (r"\usepackage{iftex}", r"\RequirePackage{iftex}")
        for index in [text.find(needle)]
        if index != -1
    ]
    return min(matches) if matches else -1


def _has_unescaped_ampersand(text: str) -> bool:
    for index, char in enumerate(text):
        if char != "&":
            continue
        backslashes = 0
        cursor = index - 1
        while cursor >= 0 and text[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2 == 0:
            return True
    return False


def _guard_lines_for_pdftex(text: str, pattern: re.Pattern[str]) -> str:
    """Wrap matching bare lines in \\ifPDFTeX while leaving guarded lines alone."""

    output: list[str] = []
    pdftex_depth = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        inside_pdftex = pdftex_depth > 0
        if stripped == r"\ifPDFTeX":
            pdftex_depth += 1

        if pattern.match(line) and not inside_pdftex:
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
    return (
        "\\usepackage{iftex}" in lowered
        or "\\usepackage[iftex]" in lowered
        or "\\requirepackage{iftex}" in lowered
    )


def _insert_after_documentclass(text: str, insertion: str) -> str:
    match = DOCUMENTCLASS_RE.search(text)
    if not match:
        return text
    return text[: match.end()] + "\n" + insertion + text[match.end() :]
