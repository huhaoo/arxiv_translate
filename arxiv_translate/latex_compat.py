from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from .latex_scan import contains_unescaped, line_ending
from .source_files import (
    LATEX_DEFINITION_SUFFIXES,
    LATEX_DOCUMENT_SUFFIXES,
    iter_source_files,
)

DOCUMENTCLASS_RE = re.compile(r"\\documentclass(?:\[[^\]]*\])?\{[^}]+\}")
PDFOUTPUT_RE = re.compile(r"(?m)^(?P<indent>\s*)\\pdfoutput\s*=\s*(?P<value>\d+)\s*$")
PDFMINORVERSION_RE = re.compile(
    r"^\s*\\pdfminorversion\s*=\s*\d+\s*(?:%[^\r\n]*)?$"
)
PDFTEX_ASSIGNMENT_RE = re.compile(r"^\s*\\(?:pdfoutput|pdfminorversion)\b")
BBM_PACKAGE_RE = re.compile(
    r"(?m)^(?P<indent>\s*)\\usepackage(?P<options>\[[^\]]*\])?\{bbm\}(?P<tail>\s*(?:%.*)?)$"
)
MICROTYPE_PACKAGE_RE = re.compile(
    r"^\s*(?:\\AtEndOfClass\{)?\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{microtype\}"
)
CJKUTF8_PACKAGE_RE = re.compile(
    r"(?m)^(?P<indent>\s*)\\usepackage(?P<options>\[[^\]]*\])?\{CJKutf8\}(?P<tail>\s*(?:%.*)?)$"
)
MINTED_PACKAGE_RE = re.compile(
    r"(?m)^(?P<indent>\s*)\\usepackage(?:\[[^\]]*\])?\{minted\}"
    r"(?P<tail>\s*(?:%.*)?)$"
)
MINTED_COMMAND_RE = re.compile(
    r"\\(?:inputminted|mintinline|newminted|newmintinline|newmintedfile)\b"
)
SOUL_PACKAGE_RE = re.compile(
    r"(?m)^(?P<indent>\s*)\\usepackage(?:\[[^\]]*\])?\{soul(?:utf8)?\}"
    r"(?P<tail>\s*(?:%.*)?)$"
)
PACKAGE_LOAD_RE = re.compile(
    r"(?m)^(?P<indent>[ \t]*)\\(?P<command>usepackage|RequirePackage)"
    r"[ \t]*(?:\[(?P<options>[^\]]*)\])?[ \t]*"
    r"\{(?P<packages>[^{}\r\n]+)\}"
    r"(?P<tail>[ \t]*(?:%[^\r\n]*)?)(?P<newline>\r?\n|$)"
)
PASS_OPTIONS_RE = re.compile(
    r"(?m)^(?P<indent>[ \t]*)\\PassOptionsToPackage"
    r"\{(?P<options>[^\r\n]*)\}\{(?P<package>[^{}\s,]+)\}"
    r"(?P<tail>[ \t]*(?:%[^\r\n]*)?)(?P<newline>\r?\n|$)"
)
GRAPHICS_DRIVER_OPTIONS = {
    "dvipdf",
    "dvipdfm",
    "dvipdfmx",
    "dvips",
    "dvipsone",
    "dviwin",
    "emtex",
    "luatex",
    "pdftex",
    "pctex32",
    "pctexhp",
    "pctexps",
    "textures",
    "truetex",
    "vtex",
    "xetex",
}
TEX_IF_RE = re.compile(r"^\\if[A-Za-z@]*(?=\s|\\|$)")
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
MINTED_ENVIRONMENT_FALLBACK = (
    "\\usepackage{fvextra}\n"
    "\\newenvironment{minted}[2][]{%\n"
    "  \\VerbatimEnvironment\n"
    "  \\begin{Verbatim}[breaklines=true,breakanywhere=true]%\n"
    "}{%\n"
    "  \\end{Verbatim}%\n"
    "}"
)
DISABLE_LIGATURES_SHIM = r"\providecommand{\DisableLigatures}[2][]{}"
SOUL_XETEX_HIGHLIGHT_MARKER = "arxiv-translate: XeTeX-safe CJK highlighting"
DECLARE_UNICODE_CHARACTER_RE = re.compile(r"^\s*\\DeclareUnicodeCharacter\b")
LATEX_COMPAT_SUFFIXES = LATEX_DEFINITION_SUFFIXES
STANDARD_ZERO_ARG_MACROS = {
    "bfseries",
    "centering",
    "footnotesize",
    "huge",
    "Huge",
    "itshape",
    "large",
    "Large",
    "LARGE",
    "mdseries",
    "noindent",
    "normalfont",
    "normalsize",
    "raggedleft",
    "raggedright",
    "rmfamily",
    "scshape",
    "scriptsize",
    "sffamily",
    "slshape",
    "small",
    "tiny",
    "ttfamily",
    "upshape",
}
COMMAND_DEFINITION_RE = re.compile(
    r"\\(?:newcommand|renewcommand|providecommand|DeclareRobustCommand)"
    r"\*?\s*"
    r"(?:\{\s*\\(?P<braced>[A-Za-z@]+)\s*\}|\\(?P<bare>[A-Za-z@]+))"
    r"\s*(?:\[\s*(?P<arity>\d+)\s*\])?"
)
DEF_DEFINITION_RE = re.compile(
    r"\\(?:def|gdef|edef|xdef)\s*\\(?P<name>[A-Za-z@]+)"
    r"(?P<parameters>[^{}\r\n]*)\{"
)


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

    tex_files = list(iter_source_files(root, LATEX_DEFINITION_SUFFIXES))
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
            file_suffix=path.suffix.lower(),
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
    file_suffix: str = ".tex",
    zero_arg_macro_names: set[str] | None = None,
) -> str:
    """Guard common pdfTeX-only preamble commands before XeLaTeX compilation."""

    if file_suffix in LATEX_DOCUMENT_SUFFIXES:
        text = escape_unescaped_numeric_percentages(text)
    text = remove_blank_lines_in_multiline_usepackage_options(text)
    text = remove_explicit_graphics_driver_options(text)
    text = replace_soul_highlight_for_xelatex(text)
    text = normalize_duplicate_package_loads(text)
    text = downgrade_unaligned_align_environments(text)
    text = remove_blank_lines_in_math_environments(text)
    text = replace_px_units_with_pt(text)
    text = close_unclosed_preamble_single_line_commands(text)
    text = protect_zero_arg_macros_before_nonascii(text, zero_arg_macro_names)
    text = prefer_numeric_natbib_for_numeric_bibliography_styles(text)
    text = prefer_fandol_ctex_for_xelatex(text)
    text = guard_pdfoutput_for_xelatex(text)
    text = guard_pdfminorversion_for_xelatex(text)
    text = guard_declare_unicode_character_for_xelatex(text)
    text = guard_microtype_for_xelatex(text)
    text = guard_cjkutf8_for_xelatex(text)
    text = replace_minted_environment_with_fvextra(text)
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


def guard_pdfminorversion_for_xelatex(text: str) -> str:
    """Wrap bare pdfTeX-only \\pdfminorversion assignments for XeLaTeX."""

    if "\\pdfminorversion" not in text:
        return text
    return _guard_lines_for_pdftex(text, PDFMINORVERSION_RE)


def guard_declare_unicode_character_for_xelatex(text: str) -> str:
    """Wrap bare \\DeclareUnicodeCharacter lines for XeLaTeX compatibility."""

    if "\\DeclareUnicodeCharacter" not in text:
        return text

    return _guard_lines_for_pdftex(text, DECLARE_UNICODE_CHARACTER_RE)


def guard_microtype_for_xelatex(text: str) -> str:
    """Load microtype only under pdfTeX to avoid XeTeX font patch failures."""

    if "\\usepackage{microtype}" not in text and "{microtype}" not in text:
        return text

    text = _guard_lines_for_pdftex(text, MICROTYPE_PACKAGE_RE)
    if (
        r"\DisableLigatures" in text
        and DISABLE_LIGATURES_SHIM not in text
    ):
        text = text.replace(
            r"\DisableLigatures",
            DISABLE_LIGATURES_SHIM + "\n" + r"\DisableLigatures",
            1,
        )
    return text


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


def replace_minted_environment_with_fvextra(text: str) -> str:
    """Use a shell-escape-free fallback for plain minted environments."""

    if r"\begin{minted}" not in text or MINTED_PACKAGE_RE.search(text) is None:
        return text
    if MINTED_COMMAND_RE.search(text):
        return text

    def replace(match: re.Match[str]) -> str:
        indent = match.group("indent")
        tail = match.group("tail")
        fallback = "\n".join(
            f"{indent}{line}" for line in MINTED_ENVIRONMENT_FALLBACK.splitlines()
        )
        return f"{fallback}{tail}"

    return MINTED_PACKAGE_RE.sub(replace, text, count=1)


def replace_soul_highlight_for_xelatex(text: str) -> str:
    """Use color boxes when soul highlighting would parse CJK text."""

    if (
        r"\hl{" not in text
        and r"\soulhl{" not in text
    ):
        return text
    if (
        SOUL_PACKAGE_RE.search(text) is None
        or SOUL_XETEX_HIGHLIGHT_MARKER in text
        or not _contains_cjk_character(text)
    ):
        return text
    command = "soulhl" if r"\soulhl{" in text else "hl"
    shim = (
        "% arxiv-translate: XeTeX-safe CJK highlighting\n"
        "\\RequirePackage{xcolor}\n"
        "\\def\\AXTHighlightColor{yellow}\n"
        "\\AtBeginDocument{%\n"
        "  \\renewcommand{\\sethlcolor}[1]{\\def\\AXTHighlightColor{#1}}%\n"
        f"  \\renewcommand{{\\{command}}}[1]"
        "{\\colorbox{\\AXTHighlightColor}{#1}}%\n"
        "}"
    )

    def replace(match: re.Match[str]) -> str:
        return (
            match.group(0)
            + "\n"
            + shim
        )

    return SOUL_PACKAGE_RE.sub(replace, text, count=1)


def _contains_cjk_character(text: str) -> bool:
    return any(
        "\u3400" <= char <= "\u9fff"
        or "\uf900" <= char <= "\ufaff"
        for char in text
    )


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


def remove_explicit_graphics_driver_options(text: str) -> str:
    """Let XeLaTeX select the graphics driver instead of forcing another engine."""

    def replace_package(match: re.Match[str]) -> str:
        packages = _package_names(match)
        if not {"graphics", "graphicx"}.intersection(packages):
            return match.group(0)
        options = _split_top_level_commas(match.group("options") or "")
        retained = [
            option
            for option in options
            if option.strip().lower() not in GRAPHICS_DRIVER_OPTIONS
        ]
        if len(retained) == len(options):
            return match.group(0)
        option_text = f"[{','.join(retained)}]" if retained else ""
        return (
            f"{match.group('indent')}\\{match.group('command')}{option_text}"
            f"{{{match.group('packages')}}}{match.group('tail')}"
            f"{match.group('newline')}"
        )

    text = PACKAGE_LOAD_RE.sub(replace_package, text)

    def replace_pass_options(match: re.Match[str]) -> str:
        if match.group("package").strip() not in {"graphics", "graphicx"}:
            return match.group(0)
        options = _split_top_level_commas(match.group("options"))
        retained = [
            option
            for option in options
            if option.strip().lower() not in GRAPHICS_DRIVER_OPTIONS
        ]
        if len(retained) == len(options):
            return match.group(0)
        if not retained:
            return ""
        return (
            f"{match.group('indent')}\\PassOptionsToPackage"
            f"{{{','.join(retained)}}}{{{match.group('package')}}}"
            f"{match.group('tail')}{match.group('newline')}"
        )

    return PASS_OPTIONS_RE.sub(replace_pass_options, text)


def normalize_duplicate_package_loads(text: str) -> str:
    """Deduplicate top-level package loads and pass later options up front."""

    loads = _top_level_matches(text, PACKAGE_LOAD_RE, stop_at_document=True)
    occurrences: dict[str, int] = {}
    first_seen_order: list[str] = []
    for match in loads:
        for package in _package_names(match):
            occurrences[package] = occurrences.get(package, 0) + 1
            if package not in first_seen_order:
                first_seen_order.append(package)

    duplicates = {
        package for package, occurrence_count in occurrences.items()
        if occurrence_count > 1
    }
    if not duplicates:
        return text

    options_by_package: dict[str, list[str]] = {package: [] for package in duplicates}
    for match in loads:
        options = match.group("options") or ""
        for package in _package_names(match):
            if package in duplicates:
                options_by_package[package].append(options)

    seen: set[str] = set()
    output: list[str] = []
    cursor = 0
    for match in loads:
        packages = _package_names(match)
        remaining: list[str] = []
        changed = False
        for package in packages:
            if package not in duplicates or package not in seen:
                remaining.append(package)
                seen.add(package)
            else:
                changed = True

        output.append(text[cursor : match.start()])
        if not changed:
            output.append(match.group(0))
        elif remaining:
            option_text = (
                f"[{match.group('options')}]" if match.group("options") is not None else ""
            )
            output.append(
                f"{match.group('indent')}\\{match.group('command')}{option_text}"
                f"{{{','.join(remaining)}}}{match.group('tail')}"
                f"{match.group('newline')}"
            )
        elif "%" in match.group("tail"):
            output.append(
                f"{match.group('indent')}{match.group('tail').lstrip()}"
                f"{match.group('newline')}"
            )
        cursor = match.end()
    output.append(text[cursor:])
    text = "".join(output)

    existing_options: dict[str, list[str]] = {}
    for match in _top_level_matches(text, PASS_OPTIONS_RE):
        package = match.group("package").strip()
        existing_options.setdefault(package, []).append(match.group("options"))

    pass_lines: list[str] = []
    for package in first_seen_order:
        if package not in duplicates:
            continue
        options = _ordered_package_options(options_by_package[package])
        already_passed = set(
            _ordered_package_options(existing_options.get(package, []))
        )
        missing = [option for option in options if option not in already_passed]
        if missing:
            pass_lines.append(
                f"\\PassOptionsToPackage{{{','.join(missing)}}}{{{package}}}\n"
            )

    if not pass_lines:
        return text

    documentclass = DOCUMENTCLASS_RE.search(text)
    if documentclass:
        insertion_index = documentclass.start()
    else:
        remaining_loads = _top_level_matches(text, PACKAGE_LOAD_RE)
        relevant_loads = [
            match
            for match in remaining_loads
            if duplicates.intersection(_package_names(match))
        ]
        if not relevant_loads:
            return text
        insertion_index = relevant_loads[0].start()
    return text[:insertion_index] + "".join(pass_lines) + text[insertion_index:]


def _ordered_package_options(option_groups: Iterable[str]) -> list[str]:
    options: list[str] = []
    for group in option_groups:
        for option in _split_top_level_commas(group):
            option = option.strip()
            if option and option not in options:
                options.append(option)
    return options


def _package_names(match: re.Match[str]) -> list[str]:
    return [
        package.strip()
        for package in match.group("packages").split(",")
        if package.strip()
    ]


def _split_top_level_commas(value: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif char in "{[(":
            depth += 1
        elif char in "}])":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            parts.append(value[start:index])
            start = index + 1
    parts.append(value[start:])
    return parts


def _top_level_matches(
    text: str,
    pattern: re.Pattern[str],
    *,
    stop_at_document: bool = False,
) -> list[re.Match[str]]:
    depth_by_line = _conditional_depth_by_line(text)
    document_start = text.find(r"\begin{document}") if stop_at_document else -1
    return [
        match
        for match in pattern.finditer(text)
        if (document_start == -1 or match.start() < document_start)
        and depth_by_line.get(_line_start(text, match.start()), 0) == 0
    ]


def _conditional_depth_by_line(text: str) -> dict[int, int]:
    depths: dict[int, int] = {}
    depth = 0
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith(r"\fi") and (
            len(stripped) == 3 or not stripped[3].isalpha()
        ):
            depth = max(0, depth - 1)
        depths[offset] = depth
        if TEX_IF_RE.match(stripped):
            depth += 1
        offset += len(line)
    return depths


def _line_start(text: str, index: int) -> int:
    newline = text.rfind("\n", 0, index)
    return 0 if newline == -1 else newline + 1


def downgrade_unaligned_align_environments(text: str) -> str:
    """Use equation for align environments that have no alignment points."""

    def replace(match: re.Match[str]) -> str:
        environment = match.group(1)
        body = match.group(2)
        if contains_unescaped(body, "&"):
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

    output: list[str] = []
    for line in text.splitlines(keepends=True):
        if PDFTEX_ASSIGNMENT_RE.match(line):
            output.append(line)
            continue
        output.append(
            re.sub(r"(?<!\\)(\d)\s*%(?=[ \t]*(?:\S|\r?\n|$))", r"\1\\%", line)
        )
    return "".join(output)


def close_unclosed_preamble_single_line_commands(text: str) -> str:
    """Close short preamble commands that translation accidentally left open."""

    lines = text.splitlines(keepends=True)
    output: list[str] = []
    for index, line in enumerate(lines):
        fixed = line
        if re.match(r"^\s*\\(?:title|date)\{", line):
            missing = _missing_closing_braces(line)
            if missing > 0 and _next_nonblank_is_preamble_boundary(lines, index + 1):
                ending = line_ending(line)
                body = line[: -len(ending)] if ending else line
                fixed = body.rstrip() + ("}" * missing) + ending
        output.append(fixed)
    return "".join(output)


def protect_zero_arg_macros_before_nonascii(
    text: str,
    macro_names: set[str] | None = None,
) -> str:
    """Add an empty group after no-argument macros before CJK/non-ASCII text."""

    names = set(STANDARD_ZERO_ARG_MACROS)
    names.update(macro_names or set())
    names.update(_zero_arg_macro_names(text))
    if not names:
        return text

    macro_pattern = "|".join(
        re.escape(name) for name in sorted(names, key=len, reverse=True)
    )
    pattern = re.compile(
        rf"\\({macro_pattern})(?:\\(?=[^\x00-\x7F])|(?=[^\x00-\x7F]))"
    )
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
    names: set[str] = set()
    for match in COMMAND_DEFINITION_RE.finditer(text):
        if match.group("arity") not in {None, "0"}:
            continue
        names.add(match.group("braced") or match.group("bare"))
    for match in DEF_DEFINITION_RE.finditer(text):
        if "#" not in match.group("parameters"):
            names.add(match.group("name"))
    return names


def _is_macro_definition_line(line: str) -> bool:
    return bool(COMMAND_DEFINITION_RE.search(line) or DEF_DEFINITION_RE.search(line))


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
