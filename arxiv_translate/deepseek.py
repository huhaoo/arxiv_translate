from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from socket import timeout as SocketTimeout
from dataclasses import dataclass
from typing import Callable

from .errors import DeepSeekError
from .preserved_terms import format_preserved_terms_for_prompt, strip_preserved_terms

INTERNAL_PROMPT_TAG_RE = re.compile(
    r"</?(?:CURRENT_FRAGMENT|PREVIOUS_CONTEXT|NEXT_CONTEXT|PAPER_TRANSLATION_GUIDE)\s*>"
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


GUIDE_SYSTEM_PROMPT = """You are a senior academic translator preparing a translation guide for a LaTeX research paper.
Analyze the complete paper source and produce a concise guide that will be prepended to later chunk-by-chunk translation prompts.

Follow these rules:
- Do not translate the paper.
- Do not include long quotations from the paper.
- Prefer stable, reusable guidance over paragraph-specific commentary.
- If uncertain about a term, mark it as "keep English" or "needs context" instead of guessing.
- Preserve all mathematical symbols, labels, citations, theorem names, author names, arXiv IDs, DOIs, package names, file names, and code identifiers.
- Output Markdown only, with the exact section headings requested."""


SYSTEM_PROMPT = """You are a strict LaTeX-to-Chinese translation engine.
Your task is to translate only human-readable English prose into Simplified Chinese while preserving a compilable LaTeX fragment.

Output rules:
- Return only the translated LaTeX fragment.
- Do not add markdown fences, explanations, summaries, notes, or surrounding text.
- Never output the XML-like boundary markers used in the prompt, including
  <CURRENT_FRAGMENT>, </CURRENT_FRAGMENT>, <PREVIOUS_CONTEXT>,
  </PREVIOUS_CONTEXT>, <NEXT_CONTEXT>, </NEXT_CONTEXT>,
  <PAPER_TRANSLATION_GUIDE>, or </PAPER_TRANSLATION_GUIDE>.
- Follow the paper translation guide when it is provided.
- When previous/next context is provided, use it only for terminology and coherence.
- Never translate, paraphrase, copy, repeat, or output the previous/next context.
- Output exactly one translation of the current fragment; do not duplicate any sentence or paragraph.
- Do not leave ordinary English prose untranslated. If a sentence is visible article prose, translate it to Simplified Chinese.
- Keep paragraph boundaries, line breaks, indentation, and ordering as close to the input as possible.
- If a fragment is mostly LaTeX structure, math, code, bibliography data, or generated auxiliary content, return it unchanged except for clear prose.

Translate:
- Article prose, abstracts, theorem statements, proof prose, captions, section titles, item text, and table cell prose.
- Natural-language comments only when they are explanatory text for readers.

Preserve exactly:
- All LaTeX commands and environment names, including backslashes, braces, optional arguments, and command order.
- Labels, refs, citations, bibliography keys, anchors, counters, and cross-reference identifiers.
- Math expressions and math environments: $...$, $$...$$, \\(...\\), \\[...\\], equation, align, gather, multline, cases, array, matrix, theorem-like math displays, and all math symbols.
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

    def generate_paper_guide(self, latex_document: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": GUIDE_SYSTEM_PROMPT},
                {"role": "user", "content": _guide_request(latex_document)},
            ],
            "temperature": 0.1,
        }

        for attempt in range(1, self.retries + 1):
            try:
                return self._post(payload).strip()
            except DeepSeekError as exc:
                if attempt == self.retries:
                    raise
                if exc.retryable:
                    time.sleep(_retry_delay(exc, attempt))

        raise DeepSeekError("paper guide generation failed after retries")

    def translate_latex(
        self,
        fragment: str,
        context_before: str = "",
        context_after: str = "",
        paper_guide: str = "",
        warning_logger: Callable[[str], None] | None = None,
    ) -> str:
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
                content = self._post(payload)
                validate_translation_protocol(content)
                untranslated = find_untranslated_english_warning(content, fragment)
                if not untranslated:
                    return content
                untranslated_warnings += 1
                last_untranslated_content = content
                retry_warning = (
                    "The previous response left a long English prose span untranslated: "
                    f"{untranslated}"
                )
                if untranslated_warnings >= self.retries:
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
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
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


@dataclass
class DeepSeekFailoverClient:
    clients: list[DeepSeekClient]
    label: str = "DeepSeek"
    switch_logger: Callable[[str], None] | None = None
    warning_logger: Callable[[str], None] | None = None

    @property
    def model(self) -> str:
        return "failover:" + ",".join(client.model for client in self.clients)

    def generate_paper_guide(self, latex_document: str) -> str:
        return self._call(
            "paper guide generation",
            lambda client: client.generate_paper_guide(latex_document),
        )

    def translate_latex(
        self,
        fragment: str,
        context_before: str = "",
        context_after: str = "",
        paper_guide: str = "",
    ) -> str:
        return self._call(
            "translation",
            lambda client: client.translate_latex(
                fragment,
                context_before=context_before,
                context_after=context_after,
                paper_guide=paper_guide,
                warning_logger=self.warning_logger,
            ),
        )

    def _call(self, operation_name: str, operation):
        if not self.clients:
            raise DeepSeekError(f"{self.label} has no configured clients")

        errors: list[str] = []
        for index, client in enumerate(self.clients):
            try:
                result = operation(client)
            except DeepSeekError as exc:
                errors.append(f"#{index + 1} model={client.model}: {exc}")
                if index + 1 < len(self.clients):
                    self._log_switch(index, client, exc)
                continue
            return result

        raise DeepSeekError(
            f"{self.label} {operation_name} failed for all configs: "
            + " | ".join(errors)
        )

    def _log_switch(self, index: int, client: DeepSeekClient, exc: DeepSeekError) -> None:
        if self.switch_logger is None:
            return
        self.switch_logger(
            f"{self.label}: config #{index + 1} "
            f"{_base_url_host(client.base_url)} model={client.model} failed; "
            f"trying config #{index + 2}. reason: {_short_error(exc)}"
        )


def validate_translation_response(content: str, source_fragment: str = "") -> str:
    """Reject wrapper text that would make translation output unsafe."""

    validate_translation_protocol(content)
    return content


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


def _short_error(exc: DeepSeekError) -> str:
    message = " ".join(str(exc).split())
    if len(message) > 180:
        return message[:177] + "..."
    return message


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
    preserved_terms = format_preserved_terms_for_prompt()
    retry_block = ""
    if retry_warning:
        retry_block = (
            "Previous response was rejected by the caller because it violated "
            f"the output protocol: {retry_warning}\n"
            "Retry by returning raw LaTeX only. Do not wrap the answer in "
            "markdown fences, XML tags, explanations, or any other boundary text.\n\n"
        )

    return retry_block + (
        "Translate only the LaTeX in <CURRENT_FRAGMENT> into Simplified Chinese.\n"
        "The angle-bracket markers are delimiters for the prompt only. "
        "They are not LaTeX and must never appear in your answer.\n"
        "If <PAPER_TRANSLATION_GUIDE> is provided, follow its terminology and style. "
        "The guide is reference material, not content to translate or output.\n"
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
        "<PAPER_TRANSLATION_GUIDE>, </PAPER_TRANSLATION_GUIDE>, ```.\n\n"
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


def _guide_request(latex_document: str) -> str:
    preserved_terms = format_preserved_terms_for_prompt()
    return (
        "Create a concise translation guide for this complete LaTeX paper.\n"
        "Use the following exact Markdown headings and keep the guide practical for later chunk translation.\n"
        "Do not translate the paper itself.\n\n"
        f"The following technical terms must remain in English when they appear as terms: {preserved_terms}.\n\n"
        "Required output format:\n"
        "# Paper Translation Guide\n"
        "## One-Sentence Topic\n"
        "A single sentence in Simplified Chinese describing the paper.\n"
        "## Structure\n"
        "- Bullet list of major sections or logical parts.\n"
        "## Glossary\n"
        "| English term | Chinese translation | Notes |\n"
        "| --- | --- | --- |\n"
        "Include core technical terms, theorem/result names, graph/math/statistical terms, and recurring phrases.\n"
        "## Proper Nouns And Keep-English Items\n"
        "- Names, software/packages, datasets, commands, labels, symbols, and terms that should remain in English or LaTeX.\n"
        "## Style Rules\n"
        "- Rules for tone, mathematical style, terminology consistency, and what not to translate.\n"
        "## LaTeX Cautions\n"
        "- Specific macros, environments, code blocks, tables, figures, captions, or bibliography areas that require extra care.\n\n"
        "<COMPLETE_LATEX_SOURCE>\n"
        f"{latex_document}\n"
        "</COMPLETE_LATEX_SOURCE>"
    )
