from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from socket import timeout as SocketTimeout
from collections import Counter
from dataclasses import dataclass
from typing import Callable

from .errors import DeepSeekError
from .latex_scan import is_escaped, visible_latex_line
from .network import urlopen
from .preferred_translations import format_preferred_translations_for_prompt
from .preserved_terms import format_preserved_terms_for_prompt, strip_preserved_terms

INTERNAL_PROMPT_TAG_RE = re.compile(
    r"(?:"
    r"</?(?:CURRENT_FRAGMENT|PREVIOUS_CONTEXT|NEXT_CONTEXT|PAPER_TRANSLATION_GUIDE)\s*>"
    r"|\\(?:begin|end)\{(?:CURRENT_FRAGMENT|PREVIOUS_CONTEXT|NEXT_CONTEXT|PAPER_TRANSLATION_GUIDE)\}"
    r")"
)
LATEX_BACKTICK_QUOTE_RE = re.compile(r"`|\\`|\\'")
STRUCTURAL_IDENTIFIER_ARG_RE = re.compile(
    r"\\(?P<command>"
    r"(?:label|ref|eqref|cref|Cref|autoref|cite|citep|citet|citealp|citealt|"
    r"citeauthor|citeyear|citeyearpar)"
    r"\*?(?:\[[^\[\]{}]*\])*"
    r")\{(?P<arg>[^{}]*)\}"
)
ENVIRONMENT_BOUNDARY_RE = re.compile(r"\\(?P<command>begin|end)\{(?P<name>[^{}]+)\}")
LATEX_COMMAND_RE = re.compile(r"(?<!\\)\\(?P<name>[A-Za-z@]+)")
LATEX_COMMAND_CJK_BOUNDARY_RE = re.compile(
    r"(?<!\\)\\(?P<command>[A-Za-z@]+)(?=[\u3400-\u9fff])"
)
UNTRANSLATED_ENGLISH_RE = re.compile(
    r"\b[A-Za-z][A-Za-z'-]{2,}"
    r"(?:[ \t\r\n,;:()\-]+[A-Za-z][A-Za-z'-]{2,}){11,}\b"
)
ENGLISH_WORD_RE = re.compile(r"\b[A-Za-z][A-Za-z'-]{2,}\b")
SKIP_UNTRANSLATED_CHECK_ENVIRONMENTS = {
    "alltt",
    "filecontents",
    "filecontents*",
    "lstlisting",
    "minted",
    "Verbatim",
    "verbatim",
}
NONSTRUCTURAL_TEXT_COMMANDS = {
    "bf",
    "em",
    "emph",
    "it",
    "md",
    "rm",
    "sc",
    "sf",
    "sl",
    "textbf",
    "textit",
    "textmd",
    "textnormal",
    "textrm",
    "textsc",
    "textsf",
    "textsl",
    "texttt",
    "textup",
    "tt",
    "underline",
    "up",
}


SYSTEM_PROMPT = """You are a strict LaTeX-to-Chinese translation engine.
Your task is to translate only human-readable English prose into Simplified Chinese while preserving a compilable LaTeX fragment.

Output rules:
- Return only the translated LaTeX fragment.
- Do not add markdown fences, explanations, summaries, notes, or surrounding text.
- Never output the XML-like boundary markers used in the prompt, including
  <CURRENT_FRAGMENT>, </CURRENT_FRAGMENT>, <PREVIOUS_CONTEXT>,
  </PREVIOUS_CONTEXT>, <NEXT_CONTEXT>, </NEXT_CONTEXT>,
  <PAPER_TRANSLATION_GUIDE>, or </PAPER_TRANSLATION_GUIDE>.
- Never convert prompt boundary markers into LaTeX environments such as
  \\begin{CURRENT_FRAGMENT} or \\end{CURRENT_FRAGMENT}.
- Follow the paper translation guide when it is provided.
- When previous/next context is provided, use it only for terminology and coherence.
- Never translate, paraphrase, copy, repeat, or output the previous/next context.
- Output exactly one translation of the current fragment; do not duplicate any sentence or paragraph.
- Do not leave ordinary English prose untranslated. If a sentence is visible article prose, translate it to Simplified Chinese.
- Keep paragraph boundaries, line breaks, indentation, and ordering as close to the input as possible.
- The current fragment is an arbitrary block from a larger LaTeX document. Its \\begin{...} and \\end{...} commands may intentionally be unpaired.
- Never add, remove, rename, move, or complete any \\begin{...} or \\end{...} command. Preserve every environment boundary exactly as it appears.
- If a fragment is mostly LaTeX structure, math, code, bibliography data, or generated auxiliary content, return it unchanged except for clear prose.

Translate:
- Article prose, abstracts, theorem statements, proof prose, captions, section titles, item text, and table cell prose.
- Natural-language comments only when they are explanatory text for readers.

Preserve exactly:
- All LaTeX commands and environment names, including backslashes, braces, optional arguments, and command order.
- Preserve legacy font declarations such as \\it, \\bf, \\rm, \\em, \\sc, \\sf, \\sl, and \\tt exactly. Do not modernize them to \\textit, \\textbf, or similar commands.
- Labels, refs, citations, bibliography keys, anchors, counters, and cross-reference identifiers.
- Never escape underscores in labels, refs, citations, or bibliography keys. Keep identifiers like section:sparse_autoencoder, not section:sparse\\_autoencoder.
- Do not use LaTeX backtick quotes in translated prose. Convert quoted visible
  prose to ordinary text quotes: use ASCII double quotes (") for double quotes
  and right single quote (’) for single quotes. Never output any backtick
  character, doubled backticks, or backslash-prefixed quote punctuation.
- Math expressions and math environments: $...$, $$...$$, \\(...\\), \\[...\\], equation, align, gather, multline, cases, cases*, array, matrix, theorem-like math displays, and all math symbols.
- Never replace LaTeX math commands such as \\sim with Unicode math symbols such as ∼.
- In math-mode portions of display environments such as equation, align, gather, multline, split, and cases, do not wrap symbols in additional $...$ delimiters. For example, keep i \\in x_t directly in math mode.
- Do not assume every nested cell or argument inside a display environment is in math mode. Preserve text-mode islands such as \\text{...} and \\mbox{...}. In mathtools cases*, the second column is text mode; when translated prose in that column contains math, retain or add inline math delimiters required for valid LaTeX, for example: & 如果 $r \\neq r'$ \\\\.
- Distinguish cases from cases*: ordinary cases columns are math mode, while the condition column of cases* is text mode.
- Graphics, file paths, URLs, package names, class names, option names, and input/include targets.
- Table structure: &, \\\\, \\hline, \\cline, \\multicolumn, \\multirow, column specs, alignment markers, and row/column counts.
- Code and verbatim-like content: verbatim, lstlisting, minted, alltt, algorithmic code lines, shell commands, programming identifiers, and code comments inside code blocks.
- BibTeX/BibLaTeX entries, DOIs, arXiv IDs, journal names, author names, and reference metadata.
- Custom macro definitions, newcommands, renewcommands, def, let, catcode, counters, lengths, package setup, and preamble configuration.
- The complete \\title command and all of its arguments; keep the PDF title in the original English.
- Hyperref PDF title metadata such as Title={...} and pdftitle={...}; keep the PDF title in the original English.
- Internal placeholders such as \\AXTProtectedTextBox{...}; keep them unchanged.

When translating inside command arguments:
- You may translate visible prose in arguments such as \\section{...}, \\caption{...}, \\item ..., and theorem/proof text.
- Do not translate or alter arguments of structural commands such as \\label{...}, \\ref{...}, \\cite{...}, \\includegraphics{...}, \\input{...}, \\bibliography{...}, \\url{...}, \\href{...}{URL part}, \\usepackage{...}, or \\documentclass{...}.

Quality constraints:
- Maintain academic mathematical style.
- Use concise, natural Simplified Chinese.
- Do not simplify, reinterpret, add, remove, or reorder technical claims.
- If preserving LaTeX conflicts with translation, prefer preserving LaTeX exactly."""


@dataclass
class DeepSeekClient:
    api_key: str
    model: str
    base_url: str
    timeout: int = 120
    temperature: float = 0.2
    retries: int = 3
    untranslated_retries: int = 5
    use_proxy: bool = True
    warning_logger: Callable[[str], None] | None = None

    def translate_latex(
        self,
        fragment: str,
        context_before: str = "",
        context_after: str = "",
        paper_guide: str = "",
        warning_logger: Callable[[str], None] | None = None,
    ) -> str:
        warning_logger = warning_logger or self.warning_logger
        retry_warning = ""
        request_errors = 0
        untranslated_warnings = 0
        last_untranslated_content = ""
        while True:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": _translation_request(
                            fragment,
                            context_before=context_before,
                            context_after=context_after,
                            paper_guide=paper_guide,
                            retry_warning=retry_warning,
                        ),
                    },
                ],
                "temperature": self.temperature,
            }
            try:
                content = validate_translation_response(
                    self._post(payload),
                    source_fragment=fragment,
                    warning_logger=warning_logger,
                    warning_context=f"{_base_url_host(self.base_url)} model={self.model}",
                )
                untranslated = find_untranslated_english_warning(content, fragment)
                if not untranslated:
                    return content
                untranslated_warnings += 1
                last_untranslated_content = content
                retry_warning = (
                    "The previous response left a long English prose span untranslated: "
                    f"{untranslated}"
                )
                if untranslated_warnings >= self.untranslated_retries:
                    _warn_untranslated_accepted(
                        warning_logger,
                        self.model,
                        self.base_url,
                        untranslated,
                    )
                    return last_untranslated_content
                continue
            except DeepSeekError as exc:
                request_errors += 1
                if request_errors >= self.retries:
                    raise
                if exc.protocol_violation:
                    retry_warning = str(exc)
                    continue
                if exc.retryable:
                    time.sleep(_retry_delay(exc, request_errors))

        raise DeepSeekError("translation failed after retries")

    def _post(self, payload: dict) -> str:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base_url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(
                request,
                timeout=self.timeout,
                use_proxy=self.use_proxy,
            ) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            retryable = exc.code == 429 or 500 <= exc.code < 600
            raise DeepSeekError(
                f"DeepSeek API returned HTTP {exc.code}: {detail[:500]}",
                status_code=exc.code,
                retryable=retryable,
            ) from exc
        except urllib.error.URLError as exc:
            raise DeepSeekError(
                f"DeepSeek API request failed: {exc.reason}",
                retryable=True,
            ) from exc
        except SocketTimeout as exc:
            raise DeepSeekError("DeepSeek API request timed out", retryable=True) from exc
        except json.JSONDecodeError as exc:
            raise DeepSeekError("DeepSeek API returned invalid JSON") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise DeepSeekError(f"DeepSeek API response has no message: {data}") from exc
        return content

def validate_translation_response(
    content: str,
    source_fragment: str = "",
    warning_logger: Callable[[str], None] | None = None,
    warning_context: str = "",
) -> str:
    """Reject wrapper text that would make translation output unsafe."""

    content = normalize_latex_quote_punctuation(content)
    content = normalize_structural_identifier_escapes(content)
    content = normalize_latex_command_cjk_boundaries(content)
    validate_translation_protocol(content)
    validate_latex_braces_balanced(content)
    validate_environment_boundaries_preserved(content, source_fragment)
    validate_latex_commands_preserved(
        content,
        source_fragment,
        warning_logger=warning_logger,
        warning_context=warning_context,
    )
    validate_alignment_tabs_preserved(content, source_fragment)
    return content


def normalize_latex_quote_punctuation(content: str) -> str:
    """Convert LaTeX English quote punctuation to plain text quotes."""

    return (
        content.replace(r"\`\`", '"')
        .replace(r"\`", "’")
        .replace(r"\'\'", '"')
        .replace(r"\'", "’")
        .replace("``", '"')
        .replace("''", '"')
        .replace("`", "’")
    )


def normalize_structural_identifier_escapes(content: str) -> str:
    """Restore escaped underscores in LaTeX cross-reference identifiers."""

    def replace(match: re.Match[str]) -> str:
        arg = match.group("arg")
        if r"\_" not in arg:
            return match.group(0)
        return "\\" + match.group("command") + "{" + arg.replace(r"\_", "_") + "}"

    return STRUCTURAL_IDENTIFIER_ARG_RE.sub(replace, content)


def normalize_latex_command_cjk_boundaries(content: str) -> str:
    """Separate LaTeX control words from immediately following CJK text.

    XeLaTeX can treat a control word glued to Chinese text as a single
    undefined control sequence. A space after the ASCII command name keeps the
    original command while making the following Chinese text visible text again.
    """

    return LATEX_COMMAND_CJK_BOUNDARY_RE.sub(r"\\\g<command> ", content)


def validate_latex_braces_balanced(content: str) -> None:
    """Reject unbalanced grouping braces while ignoring escaped visible braces."""

    depth = 0
    backslashes = 0
    in_comment = False
    for char in content:
        if in_comment:
            if char in "\r\n":
                in_comment = False
            continue
        if char == "\\":
            backslashes += 1
            continue
        escaped = backslashes % 2 == 1
        if char == "%" and not escaped:
            in_comment = True
        elif char == "{" and not escaped:
            depth += 1
        elif char == "}" and not escaped:
            depth -= 1
            if depth < 0:
                break
        backslashes = 0
    if depth != 0:
        raise DeepSeekError(
            "DeepSeek translation returned unbalanced LaTeX braces",
            retryable=True,
            protocol_violation=True,
        )


def validate_environment_boundaries_preserved(
    content: str,
    source_fragment: str,
) -> None:
    """Reject translations that add, remove, rename, or reorder environments."""

    if not source_fragment:
        return
    source_boundaries = _environment_boundaries(source_fragment)
    translated_boundaries = _environment_boundaries(content)
    if translated_boundaries == source_boundaries:
        return
    raise DeepSeekError(
        "DeepSeek translation changed LaTeX environment boundaries",
        retryable=True,
        protocol_violation=True,
    )


def _environment_boundaries(content: str) -> list[tuple[str, str]]:
    boundaries: list[tuple[str, str]] = []
    for line in content.splitlines():
        visible = visible_latex_line(line)
        boundaries.extend(
            (match.group("command"), match.group("name"))
            for match in ENVIRONMENT_BOUNDARY_RE.finditer(visible)
        )
    return boundaries


def validate_latex_commands_preserved(
    content: str,
    source_fragment: str,
    warning_logger: Callable[[str], None] | None = None,
    warning_context: str = "",
) -> None:
    """Reject translations that add, remove, or rename LaTeX commands."""

    if not source_fragment:
        return
    source_commands = _latex_commands(source_fragment)
    translated_commands = _latex_commands(content)
    source_counts = Counter(source_commands)
    translated_counts = Counter(translated_commands)
    if translated_counts == source_counts:
        return
    source_structural_counts = _structural_latex_command_counts(source_commands)
    translated_structural_counts = _structural_latex_command_counts(translated_commands)
    if translated_structural_counts == source_structural_counts:
        _warn_nonstructural_command_change(
            warning_logger,
            warning_context,
            source_counts,
            translated_counts,
        )
        return
    missing = list((source_structural_counts - translated_structural_counts).elements())
    added = list((translated_structural_counts - source_structural_counts).elements())
    missing_summary = ", ".join(f"\\{name}" for name in missing[:5]) or "none"
    added_summary = ", ".join(f"\\{name}" for name in added[:5]) or "none"
    raise DeepSeekError(
        "DeepSeek translation changed LaTeX commands: "
        f"missing {missing_summary}; added {added_summary} "
        f"(source count {len(source_commands)}, output count "
        f"{len(translated_commands)})",
        retryable=True,
        protocol_violation=True,
    )


def _structural_latex_command_counts(commands: list[str]) -> Counter[str]:
    return Counter(
        command for command in commands if command not in NONSTRUCTURAL_TEXT_COMMANDS
    )


def _warn_nonstructural_command_change(
    warning_logger: Callable[[str], None] | None,
    warning_context: str,
    source_counts: Counter[str],
    translated_counts: Counter[str],
) -> None:
    if warning_logger is None:
        return
    missing = list((source_counts - translated_counts).elements())
    added = list((translated_counts - source_counts).elements())
    missing_summary = ", ".join(f"\\{name}" for name in missing[:5]) or "none"
    added_summary = ", ".join(f"\\{name}" for name in added[:5]) or "none"
    context = f" on {warning_context}" if warning_context else ""
    warning_logger(
        "warning: accepted translation with changed non-structural LaTeX "
        f"text commands{context}: missing {missing_summary}; added {added_summary}"
    )


def _latex_commands(content: str) -> list[str]:
    commands: list[str] = []
    for line in content.splitlines():
        visible = visible_latex_line(line)
        commands.extend(match.group("name") for match in LATEX_COMMAND_RE.finditer(visible))
    return commands


def validate_alignment_tabs_preserved(
    content: str,
    source_fragment: str,
) -> None:
    """Reject added or removed unescaped alignment tabs."""

    if not source_fragment:
        return
    source_count = _unescaped_character_count(source_fragment, "&")
    translated_count = _unescaped_character_count(content, "&")
    if translated_count == source_count:
        return
    raise DeepSeekError(
        "DeepSeek translation changed LaTeX alignment tabs: "
        f"source count {source_count}, output count {translated_count}",
        retryable=True,
        protocol_violation=True,
    )


def _unescaped_character_count(content: str, target: str) -> int:
    count = 0
    for line in content.splitlines():
        for index, char in enumerate(line):
            if char == "%" and not is_escaped(line, index):
                break
            if char == target and not is_escaped(line, index):
                count += 1
    return count


def validate_translation_protocol(content: str) -> None:
    if content.strip().startswith("```"):
        raise DeepSeekError(
            "DeepSeek translation returned a markdown fence instead of raw LaTeX",
            retryable=True,
            protocol_violation=True,
        )
    match = INTERNAL_PROMPT_TAG_RE.search(content)
    if match:
        raise DeepSeekError(
            f"DeepSeek translation echoed internal prompt tag: {match.group(0)}",
            retryable=True,
            protocol_violation=True,
        )
    match = LATEX_BACKTICK_QUOTE_RE.search(content)
    if match:
        raise DeepSeekError(
            "DeepSeek translation used LaTeX backtick/accent quote punctuation: "
            f"{match.group(0)}",
            retryable=True,
            protocol_violation=True,
        )


def find_untranslated_english_warning(content: str, source_fragment: str) -> str:
    untranslated = _find_untranslated_english_prose(content)
    if untranslated and _source_has_english_prose(source_fragment):
        return untranslated[:160]
    return ""


def _find_untranslated_english_prose(content: str) -> str:
    checked = _normalize_for_untranslated_check(content)
    match = UNTRANSLATED_ENGLISH_RE.search(checked)
    if match:
        return match.group(0)
    return _find_english_heavy_visible_span(checked)


def _source_has_english_prose(source_fragment: str) -> bool:
    return bool(_find_untranslated_english_prose(source_fragment))


def _normalize_for_untranslated_check(content: str) -> str:
    checked = _remove_skip_check_environments(content)
    checked = strip_preserved_terms(checked)
    checked = re.sub(
        r"\$\$.*?\$\$|\$.*?\$|\\\[.*?\\\]|\\\(.*?\\\)",
        " ",
        checked,
        flags=re.DOTALL,
    )
    checked = re.sub(
        r"\\(?:cite|citep|citet|citealp|ref|eqref|cref|Cref|autoref|label|url|href|includegraphics|input|include|bibliography)\*?(?:\[[^\]]*\])?(?:\{[^{}]*\}){1,2}",
        " ",
        checked,
    )
    checked = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?", " ", checked)
    checked = re.sub(r"[{}~^_\\]+", " ", checked)
    return checked


def _find_english_heavy_visible_span(content: str) -> str:
    for segment in re.split(r"[\u3400-\u9fff]+", content):
        words = ENGLISH_WORD_RE.findall(segment)
        if len(words) >= 16 and len(segment.strip()) >= 120:
            return " ".join(words[:24])
    return ""


def _remove_skip_check_environments(content: str) -> str:
    for env_name in SKIP_UNTRANSLATED_CHECK_ENVIRONMENTS:
        content = re.sub(
            rf"\\begin\{{{re.escape(env_name)}\}}.*?\\end\{{{re.escape(env_name)}\}}",
            " ",
            content,
            flags=re.DOTALL,
        )
    return content


def _base_url_host(base_url: str) -> str:
    rest = base_url.split("://", 1)[1] if "://" in base_url else base_url
    return rest.split("/", 1)[0]


def _warn_untranslated_accepted(
    warning_logger: Callable[[str], None] | None,
    model: str,
    base_url: str,
    untranslated: str,
) -> None:
    if warning_logger is None:
        return
    warning_logger(
        "warning: accepted translation after repeated untranslated-English "
        f"warnings on {_base_url_host(base_url)} model={model}. "
        f"span: {untranslated[:160]}"
    )

def _retry_delay(exc: DeepSeekError, attempt: int) -> int:
    if exc.status_code == 429:
        return min(30, 5 * attempt)
    return min(10, 2 * attempt)


def _translation_request(
    fragment: str,
    context_before: str = "",
    context_after: str = "",
    paper_guide: str = "",
    retry_warning: str = "",
) -> str:
    preferred_translations = format_preferred_translations_for_prompt()
    preserved_terms = format_preserved_terms_for_prompt()
    retry_block = ""
    if retry_warning:
        retry_block = (
            "Previous response was rejected by the caller because it violated "
            f"the output protocol: {retry_warning}\n"
            "Retry by returning raw LaTeX only. Do not wrap the answer in "
            "markdown fences, XML tags, explanations, or any other boundary text. "
            "Preserve every original LaTeX command exactly and remove any newly "
            "added command that was not present in <CURRENT_FRAGMENT>.\n\n"
        )

    return retry_block + (
        "Translate only the LaTeX in <CURRENT_FRAGMENT> into Simplified Chinese.\n"
        "The angle-bracket markers are delimiters for the prompt only. "
        "They are not LaTeX and must never appear in your answer.\n"
        "If <PAPER_TRANSLATION_GUIDE> is provided, follow its terminology and style. "
        "The guide is reference material, not content to translate or output.\n"
        f"When these technical terms appear as terms, use these preferred Chinese translations: {preferred_translations}.\n"
        "The optional <PREVIOUS_CONTEXT> and <NEXT_CONTEXT> blocks are reference "
        "context only. Do not translate them, do not output them, and do not repeat "
        "their content in the answer.\n"
        f"Keep these technical terms in English exactly when they appear as terms: {preserved_terms}.\n"
        "Translate every visible English prose sentence in <CURRENT_FRAGMENT>; "
        "do not leave an English paragraph or sentence in the output unless it is "
        "code, a URL, a citation key, a file path, a model name, or LaTeX metadata "
        "that the system prompt says to preserve.\n"
        "Return only the translated content corresponding to <CURRENT_FRAGMENT>.\n\n"
        "Before finalizing, verify that your answer contains none of these strings: "
        "<CURRENT_FRAGMENT>, </CURRENT_FRAGMENT>, <PREVIOUS_CONTEXT>, "
        "</PREVIOUS_CONTEXT>, <NEXT_CONTEXT>, </NEXT_CONTEXT>, "
        "<PAPER_TRANSLATION_GUIDE>, </PAPER_TRANSLATION_GUIDE>, ```, `, \\`, \\''.\n\n"
        "<PAPER_TRANSLATION_GUIDE>\n"
        f"{paper_guide}\n"
        "</PAPER_TRANSLATION_GUIDE>\n\n"
        "<PREVIOUS_CONTEXT>\n"
        f"{context_before}\n"
        "</PREVIOUS_CONTEXT>\n\n"
        "<NEXT_CONTEXT>\n"
        f"{context_after}\n"
        "</NEXT_CONTEXT>\n\n"
        "<CURRENT_FRAGMENT>\n"
        f"{fragment}\n"
        "</CURRENT_FRAGMENT>\n\n"
        "Return only the raw LaTeX translation of <CURRENT_FRAGMENT> above. "
        "Do not output, translate, summarize, or repeat any content from "
        "<PAPER_TRANSLATION_GUIDE>, <PREVIOUS_CONTEXT>, or <NEXT_CONTEXT>."
    )
