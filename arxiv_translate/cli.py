from __future__ import annotations

import argparse
import contextlib
import io
import shlex
import sys
import threading
from collections import Counter
from pathlib import Path

from .arxiv import download_pdf, download_source, parse_arxiv_id
from .compiler import compile_latex
from .config import DEFAULT_CONFIG_PATH, config_bool, config_string, load_config
from .deepseek import DeepSeekClient
from .endnote import write_endnote_import
from .errors import ArxivTranslateError, SourceUnavailableError
from .extract import extract_source
from .guide import generate_template_paper_guide
from .latex_compat import ensure_chinese_latex_support, ensure_latex_compatibility
from .links import path_uri
from .metadata import fetch_arxiv_metadata
from .paths import DEFAULT_OUTPUT_DIR, make_job_dir
from .source_files import contains_latex_document, iter_latex_documents
from .tex import (
    discover_main_tex,
    ensure_english_pdf_title,
    ensure_numeric_natbib_styles,
    ensure_superscript_numeric_citations,
    merge_adjacent_citations_in_dir,
)
from .translator import (
    DEFAULT_CHUNK_CHARS,
    DEFAULT_CONTEXT_CHARS,
    DEFAULT_PARALLEL_CHUNKS,
    TranslationCache,
    prepare_translated_tree,
    translate_tex_tree,
)

TRANSLATED_PDF_NAME = "translate.pdf"
TRANSLATION_WARNINGS_NAME = "translation-warnings.log"
INTERACTIVE_HISTORY_PATH = Path(".arxiv_translate_history")
_PROGRESS_LOCK = threading.Lock()
_PROGRESS_LINE_LENGTH = 0


class _TranslationWarningCollector:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._warnings: list[str] = []

    def add(self, message: str) -> None:
        with self._lock:
            self._warnings.append(message)

    def __len__(self) -> int:
        with self._lock:
            return len(self._warnings)

    def snapshot(self) -> list[str]:
        with self._lock:
            return list(self._warnings)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arxiv-translate",
        description="Download arXiv TeX source, translate it to Chinese, and rebuild the PDF.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "link",
        nargs="?",
        help="arXiv URL or ID; omit to enter interactive mode",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"directory for saved files; defaults to {DEFAULT_OUTPUT_DIR}/{{arxiv-id}}",
    )
    parser.add_argument("--main", help="main TeX file relative to the source root")
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help=f"local JSON config file; defaults to {DEFAULT_CONFIG_PATH}",
    )
    parser.add_argument(
        "--chunk-chars",
        type=int,
        default=DEFAULT_CHUNK_CHARS,
        help="maximum characters per translation request",
    )
    parser.add_argument(
        "--context-chars",
        type=int,
        default=DEFAULT_CONTEXT_CHARS,
        help="characters of previous/next context sent with each translation chunk",
    )
    parser.add_argument(
        "--parallel-chunks",
        type=int,
        default=DEFAULT_PARALLEL_CHUNKS,
        help="number of translation chunks to send concurrently",
    )
    parser.add_argument(
        "--redo",
        action="store_true",
        help="rerun the full workflow from scratch even if cached outputs already exist",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="HTTP timeout in seconds for DeepSeek requests",
    )
    parser.add_argument(
        "--no-compile",
        action="store_true",
        help="translate only; skip LaTeX compilation",
    )
    parser.add_argument(
        "-S",
        "--superscript-citations",
        "--lightcite",
        action="store_true",
        help="convert citations to a compact superscript numeric style",
    )
    parser.add_argument(
        "--keep-source-archive",
        action="store_true",
        help="keep the raw arXiv source download in the output directory",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.link:
        return run_interactive(args)

    try:
        return run(args)
    except ArxivTranslateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


def run_interactive(args: argparse.Namespace) -> int:
    history = _load_interactive_history(INTERACTIVE_HISTORY_PATH)
    print("Interactive mode. Paste one arXiv link or ID per line.")
    print("Use Up/Down for history. Press Ctrl+C/Ctrl+Z or type 'exit' to quit.")
    while True:
        try:
            link = _read_interactive_line("arxiv> ", history).strip()
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print()
            continue

        if not link:
            continue
        if link.lower() in {"exit", "quit"}:
            return 0

        item_args = _parse_interactive_args(link, args)
        if item_args is None:
            continue

        _append_interactive_history(history, link, INTERACTIVE_HISTORY_PATH)
        try:
            run(item_args)
        except ArxivTranslateError as exc:
            print(f"error: {exc}", file=sys.stderr)
        except KeyboardInterrupt:
            print("\ninterrupted", file=sys.stderr)
            return 130


def _parse_interactive_args(
    line: str,
    defaults: argparse.Namespace,
) -> argparse.Namespace | None:
    try:
        tokens = shlex.split(line)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None

    parser = build_parser()
    parser.set_defaults(**vars(defaults))
    try:
        item_args = parser.parse_args(tokens)
    except SystemExit:
        return None

    if not item_args.link:
        print("error: missing arXiv link or ID", file=sys.stderr)
        return None
    return item_args


def run(args: argparse.Namespace) -> int:
    arxiv_id = parse_arxiv_id(args.link)
    job_dir = make_job_dir(args.output_dir, arxiv_id)
    source_dir = job_dir / "source"
    translated_dir = job_dir / "translated"
    archive_path = job_dir / "source-download.bin"
    original_pdf_path = job_dir / "original.pdf"
    endnote_path = job_dir / "endnote.enw"
    guide_path = job_dir / "paper-guide.md"
    warning_collector = _TranslationWarningCollector()

    resume_from_translated = (
        not args.redo
        and _is_completed_job(job_dir, no_compile=args.no_compile)
        and _can_resume_from_translated(source_dir, translated_dir)
    )

    if args.redo:
        (job_dir / "translation-cache.json").unlink(missing_ok=True)
        guide_path.unlink(missing_ok=True)

    config = load_config(args.config)
    use_proxy = config_bool(config, "use_proxy", default=True)

    cache = TranslationCache(job_dir / "translation-cache.json")

    print(f"[1/6] arXiv id: {arxiv_id}")
    print(
        "      network: "
        + ("environment proxy" if use_proxy else "direct (proxy disabled)")
    )
    metadata = fetch_arxiv_metadata(arxiv_id, use_proxy=use_proxy)
    print(f"      title: {metadata.title}")
    if resume_from_translated:
        print(f"[2/6] reusing existing original PDF: {_display_path(job_dir)}")
        _print_file_output("original PDF", original_pdf_path, job_dir)
        print("[3/6] reusing extracted TeX source")
        tex_files = list(iter_latex_documents(source_dir))
        print(f"      found {len(tex_files)} TeX file(s)")
        original_main_tex = discover_main_tex(source_dir, args.main)
        print("[4/6] reusing translated TeX files after DeepSeek")
        translated_files = list(iter_latex_documents(translated_dir))
        print(f"      translated {len(translated_files)} file(s) already present")
    else:
        print(f"[2/6] downloading original PDF: {_display_path(job_dir)}")
        download_pdf(arxiv_id, original_pdf_path, use_proxy=use_proxy)
        _print_file_output("original PDF", original_pdf_path, job_dir)

        print("[3/6] downloading and extracting TeX source")
        try:
            download_source(arxiv_id, archive_path, use_proxy=use_proxy)
            tex_files = extract_source(archive_path, source_dir)
        except SourceUnavailableError as exc:
            print(f"      TeX source unavailable: {exc}")
            print("[4/6] skipped translation")
            print("[5/6] skipped compilation")
            print("[6/6] writing EndNote import file")
            write_endnote_import(metadata, endnote_path, [original_pdf_path])
            _print_done(endnote_path)
            return 0

        if not args.keep_source_archive:
            archive_path.unlink(missing_ok=True)
        print(f"      found {len(tex_files)} TeX file(s)")
        original_main_tex = discover_main_tex(source_dir, args.main)

        print("[4/6] generating local guide and translating TeX files with DeepSeek")
        prepare_translated_tree(source_dir, translated_dir)
        print("      guide: generating from the local template")
        paper_guide = generate_template_paper_guide(
            source_dir,
            guide_path,
            metadata,
        )
        _print_file_output("paper guide", guide_path, job_dir)
        client = _build_deepseek_client(
            config,
            model_key="deepseek_model",
            timeout=args.timeout,
            use_proxy=use_proxy,
            warning_logger=warning_collector.add,
        )
        appendix_client = _build_deepseek_client(
            config,
            model_key="deepseek_appendix_model",
            timeout=args.timeout,
            use_proxy=use_proxy,
            warning_logger=warning_collector.add,
        )
        translated_files = translate_tex_tree(
            translated_dir,
            client=client,
            cache=cache,
            chunk_chars=args.chunk_chars,
            context_chars=args.context_chars,
            parallel_chunks=args.parallel_chunks,
            paper_guide=paper_guide,
            appendix_client=appendix_client,
            progress=_print_translation_progress,
        )
        print(f"      translated {len(translated_files)} file(s)")

    main_tex = discover_main_tex(translated_dir, args.main)
    if ensure_english_pdf_title(main_tex, original_main_tex, metadata.title):
        print("      title: kept original English title")
    if args.superscript_citations:
        merged_files = merge_adjacent_citations_in_dir(translated_dir)
        if merged_files:
            print(f"      citations: merged adjacent cites in {len(merged_files)} file(s)")
        if ensure_superscript_numeric_citations(main_tex):
            print("      citations: switched to superscript numeric style")
        natbib_style_files = ensure_numeric_natbib_styles(translated_dir)
        if natbib_style_files:
            print(
                "      citations: normalized natbib styles in "
                f"{len(natbib_style_files)} template file(s)"
            )

    compatibility_files = ensure_latex_compatibility(translated_dir)
    if compatibility_files:
        print(f"      compatibility fixes: {len(compatibility_files)} file(s)")

    ensure_chinese_latex_support(main_tex)
    print(f"      main TeX: {main_tex.relative_to(translated_dir)}")

    if args.no_compile:
        print(
            "[5/6] skipped compilation; translated source: "
            f"{_display_path(translated_dir)}"
        )
        print(f"      link: {path_uri(translated_dir)}")
        print("[6/6] writing EndNote import file")
        write_endnote_import(metadata, endnote_path, [original_pdf_path])
        _print_file_output("endnote", endnote_path)
        _print_translation_warnings(warning_collector, job_dir)
        return 0

    print("[5/6] compiling translated PDF")
    translated_pdf_path = _normalize_translated_pdf(
        compile_latex(translated_dir, main_tex),
        translated_dir,
    )
    _print_file_output("translated PDF", translated_pdf_path, job_dir)

    print("[6/6] writing EndNote import file")
    write_endnote_import(
        metadata,
        endnote_path,
        [original_pdf_path, translated_pdf_path],
    )
    _print_done(endnote_path)
    _print_translation_warnings(warning_collector, job_dir)
    return 0


def _print_translation_progress(done: int, total: int, label: str) -> None:
    global _PROGRESS_LINE_LENGTH

    if total <= 0:
        return
    width = 28
    filled = min(width, int(width * done / total))
    bar = "#" * filled + "-" * (width - filled)
    message = f"      translating [{bar}] {done}/{total} {label}"
    with _PROGRESS_LOCK:
        padding = " " * max(0, _PROGRESS_LINE_LENGTH - len(message))
        print(f"\r{message}{padding}", end="", flush=True)
        _PROGRESS_LINE_LENGTH = len(message)
        if done >= total:
            print()
            _PROGRESS_LINE_LENGTH = 0


def _build_deepseek_client(
    config: dict,
    *,
    model_key: str,
    timeout: int,
    use_proxy: bool,
    warning_logger=None,
) -> DeepSeekClient:
    return DeepSeekClient(
        api_key=config_string(
            config,
            "deepseek_api_key",
            allow_empty=True,
        ),
        model=config_string(config, model_key),
        base_url=config_string(config, "deepseek_base_url"),
        timeout=timeout,
        use_proxy=use_proxy,
        warning_logger=warning_logger,
    )


def _normalize_translated_pdf(pdf_path: Path, translated_dir: Path) -> Path:
    target = translated_dir / TRANSLATED_PDF_NAME
    if pdf_path.resolve() == target.resolve():
        return target
    target.unlink(missing_ok=True)
    pdf_path.replace(target)
    return target


def _print_file_output(label: str, path: Path, base: Path | None = None) -> None:
    print(f"      {label}: {_display_path(path, base)}")
    print(f"      link: {path_uri(path)}")


def _print_done(path: Path) -> None:
    print(f"done: {_display_path(path)}")
    print(f"link: {path_uri(path)}")


def _print_translation_warnings(
    collector: _TranslationWarningCollector,
    job_dir: Path,
) -> None:
    warnings = collector.snapshot()
    warning_path = job_dir / TRANSLATION_WARNINGS_NAME
    if not warnings:
        warning_path.unlink(missing_ok=True)
        return

    counts = Counter(_warning_kind(message) for message in warnings)
    lines = [
        "Translation warnings",
        "====================",
        "",
        f"Total: {len(warnings)}",
        "",
        "Summary:",
    ]
    lines.extend(f"- {kind}: {count}" for kind, count in sorted(counts.items()))
    lines.extend(["", "Details:"])
    lines.extend(f"[{index}] {message}" for index, message in enumerate(warnings, start=1))
    warning_path.parent.mkdir(parents=True, exist_ok=True)
    warning_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = ", ".join(
        f"{count} {kind}" for kind, count in sorted(counts.items())
    )
    print(f"warnings: {len(warnings)} warning(s): {summary}")
    print(f"warning log: {_display_path(warning_path)}")
    print(f"link: {path_uri(warning_path)}")


def _warning_kind(message: str) -> str:
    message = message.removeprefix("warning: ").strip()
    return message.split(" on ", 1)[0].strip() or "warning"


def _display_path(path: Path, base: Path | None = None) -> str:
    if base is None:
        return str(path)
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _is_completed_job(job_dir: Path, no_compile: bool = False) -> bool:
    original_pdf = job_dir / "original.pdf"
    endnote = job_dir / "endnote.enw"
    translated_pdf = job_dir / "translated" / TRANSLATED_PDF_NAME
    if not original_pdf.exists() or not endnote.exists():
        return False
    if translated_pdf.exists():
        return True
    if no_compile and _contains_tex_files(job_dir / "translated"):
        return True
    return not _contains_tex_files(job_dir / "source") and not _contains_tex_files(
        job_dir / "translated"
    )


def _can_resume_from_translated(source_dir: Path, translated_dir: Path) -> bool:
    return _contains_tex_files(source_dir) and _contains_tex_files(translated_dir)


def _contains_tex_files(path: Path) -> bool:
    if not path.exists():
        return False
    return contains_latex_document(path)


def _load_interactive_history(path: Path) -> list[str]:
    try:
        loaded = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except FileNotFoundError:
        return []
    history = _deduplicate_interactive_history(loaded)
    if history != loaded:
        _write_interactive_history(history, path)
    return history


def _append_interactive_history(history: list[str], item: str, path: Path) -> None:
    item = item.strip()
    if not item:
        return
    item_key = _interactive_history_key(item)
    history[:] = [
        existing
        for existing in history
        if _interactive_history_key(existing) != item_key
    ]
    history.append(item)
    del history[:-200]
    _write_interactive_history(history, path)


def _deduplicate_interactive_history(items: list[str]) -> list[str]:
    seen: set[tuple[str, str]] = set()
    deduplicated_reversed: list[str] = []
    for item in reversed(items):
        key = _interactive_history_key(item)
        if key in seen:
            continue
        seen.add(key)
        deduplicated_reversed.append(item)
    return list(reversed(deduplicated_reversed))[-200:]


def _interactive_history_key(item: str) -> tuple[str, str]:
    try:
        tokens = shlex.split(item)
    except ValueError:
        return ("command", item)

    parser = build_parser()
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            args = parser.parse_args(tokens)
        if args.link:
            return ("arxiv", parse_arxiv_id(args.link))
    except (ArxivTranslateError, SystemExit):
        pass
    return ("command", item)


def _write_interactive_history(history: list[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(history)
    path.write_text(content + ("\n" if content else ""), encoding="utf-8")


def _read_interactive_line(prompt: str, history: list[str]) -> str:
    if sys.platform == "win32" and sys.stdin.isatty() and sys.stdout.isatty():
        return _read_windows_history_line(prompt, history)
    return input(prompt)


def _read_windows_history_line(prompt: str, history: list[str]) -> str:
    import msvcrt

    buffer = ""
    cursor = 0
    history_index = len(history)
    line_length = len(prompt)
    print(prompt, end="", flush=True)

    while True:
        char = msvcrt.getwch()
        if char in {"\x00", "\xe0"}:
            key = msvcrt.getwch()
            if key == "H" and history_index > 0:
                history_index -= 1
                buffer = history[history_index]
                cursor = len(buffer)
                line_length = _redraw_interactive_line(
                    prompt, buffer, cursor, line_length
                )
            elif key == "P":
                if history_index < len(history) - 1:
                    history_index += 1
                    next_buffer = history[history_index]
                else:
                    history_index = len(history)
                    next_buffer = ""
                buffer = next_buffer
                cursor = len(buffer)
                line_length = _redraw_interactive_line(prompt, buffer, cursor, line_length)
            elif key == "K" and cursor > 0:
                cursor -= 1
                line_length = _redraw_interactive_line(prompt, buffer, cursor, line_length)
            elif key == "M" and cursor < len(buffer):
                cursor += 1
                line_length = _redraw_interactive_line(prompt, buffer, cursor, line_length)
            elif key == "G":
                cursor = 0
                line_length = _redraw_interactive_line(prompt, buffer, cursor, line_length)
            elif key == "O":
                cursor = len(buffer)
                line_length = _redraw_interactive_line(prompt, buffer, cursor, line_length)
            elif key == "S" and cursor < len(buffer):
                buffer = buffer[:cursor] + buffer[cursor + 1 :]
                line_length = _redraw_interactive_line(prompt, buffer, cursor, line_length)
            continue
        if char == "\x03":
            print()
            return ""
        if char == "\x1a":
            raise EOFError
        if char in {"\r", "\n"}:
            print()
            return buffer
        if char == "\b":
            if cursor > 0:
                buffer = buffer[: cursor - 1] + buffer[cursor:]
                cursor -= 1
                line_length = _redraw_interactive_line(prompt, buffer, cursor, line_length)
            continue
        if char.isprintable():
            buffer = buffer[:cursor] + char + buffer[cursor:]
            cursor += len(char)
            history_index = len(history)
            line_length = _redraw_interactive_line(prompt, buffer, cursor, line_length)


def _redraw_interactive_line(
    prompt: str,
    buffer: str,
    cursor: int,
    previous_length: int,
) -> int:
    line = f"{prompt}{buffer}"
    padding = " " * max(0, previous_length - len(line))
    backspaces = len(padding) + len(buffer) - cursor
    print(f"\r{line}{padding}", end="", flush=True)
    if backspaces:
        print("\b" * backspaces, end="", flush=True)
    return len(line)


if __name__ == "__main__":
    raise SystemExit(main())
