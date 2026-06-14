from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .deepseek import DeepSeekClient, validate_translation_response
from .errors import DeepSeekError
from .preferred_translations import load_preferred_translations
from .preserved_terms import load_preserved_terms
from .tex import (
    protect_latex_text_boxes,
    restore_latex_text_boxes,
    should_translate_tex,
    split_latex_for_translation,
    strip_latex_comments,
)

DEFAULT_CHUNK_CHARS = 2048
DEFAULT_CONTEXT_CHARS = 250
DEFAULT_PARALLEL_CHUNKS = 8
class TranslationCache:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
        else:
            self.data = {}

    def get(self, text: str) -> str | None:
        with self._lock:
            return self.data.get(_hash(text))

    def put(self, source: str, translated: str) -> None:
        with self._lock:
            self.data[_hash(source)] = translated
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )


def prepare_translated_tree(source_dir: Path, translated_dir: Path) -> None:
    if translated_dir.exists():
        shutil.rmtree(translated_dir)
    shutil.copytree(source_dir, translated_dir)


def translate_tex_tree(
    root: Path,
    client: DeepSeekClient,
    cache: TranslationCache,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    context_chars: int = DEFAULT_CONTEXT_CHARS,
    parallel_chunks: int = DEFAULT_PARALLEL_CHUNKS,
    paper_guide: str = "",
    appendix_client: DeepSeekClient | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> list[Path]:
    context_chars = max(0, context_chars)
    parallel_chunks = max(1, parallel_chunks)
    translated: list[Path] = []
    tex_files = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".tex", ".ltx"}
    ]

    jobs: list[tuple[Path, str, list[str], list[str]]] = []
    for path in tex_files:
        raw = path.read_text(encoding="utf-8", errors="ignore")
        original = strip_latex_comments(raw)
        if original != raw:
            path.write_text(original, encoding="utf-8", newline="")
        protected_original, protected_text_boxes = protect_latex_text_boxes(original)
        if not should_translate_tex(protected_original):
            continue

        chunks = split_latex_for_translation(protected_original, chunk_chars)
        if chunks:
            jobs.append((path, protected_original, chunks, protected_text_boxes))

    appendix_paths = _appendix_included_paths(root, {path: original for path, original, _, _ in jobs})
    done_chunks = 0
    total_chunks = sum(len(chunks) for _, _, chunks, _ in jobs)
    outputs: dict[Path, list[str | None]] = {
        path: [None] * len(chunks) for path, _, chunks, _ in jobs
    }
    text_box_blocks: dict[Path, list[str]] = {
        path: blocks for path, _, _, blocks in jobs
    }
    work_items: list[tuple[Path, int, str, str, str, DeepSeekClient]] = []

    for path, original, chunks, _ in jobs:
        offset = 0
        for index, chunk in enumerate(chunks):
            context_before = original[max(0, offset - context_chars) : offset]
            context_after_start = offset + len(chunk)
            context_after = original[
                context_after_start : context_after_start + context_chars
            ]
            chunk_client = _client_for_chunk(
                path,
                original,
                offset,
                len(chunk),
                client,
                appendix_client,
                path.resolve() in appendix_paths,
            )
            work_items.append(
                (path, index, chunk, context_before, context_after, chunk_client)
            )
            offset += len(chunk)

    with ThreadPoolExecutor(max_workers=parallel_chunks) as executor:
        futures = [
            executor.submit(
                _translate_chunk,
                path,
                index,
                chunk,
                context_before,
                context_after,
                paper_guide,
                chunk_client,
                cache,
            )
            for (
                path,
                index,
                chunk,
                context_before,
                context_after,
                chunk_client,
            ) in work_items
        ]
        for future in as_completed(futures):
            path, index, translated_chunk = future.result()
            outputs[path][index] = translated_chunk
            done_chunks += 1
            if progress is not None:
                progress(done_chunks, total_chunks, path.name)

    for path, _, _, _ in jobs:
        out = outputs[path]
        translated_text = restore_latex_text_boxes(
            "".join(part or "" for part in out),
            text_box_blocks[path],
        )
        path.write_text(
            translated_text,
            encoding="utf-8",
            newline="",
        )
        translated.append(path)

    return translated


def _translate_chunk(
    path: Path,
    index: int,
    chunk: str,
    context_before: str,
    context_after: str,
    paper_guide: str,
    client: DeepSeekClient,
    cache: TranslationCache,
) -> tuple[Path, int, str]:
    cache_key = _cache_key(
        chunk,
        context_before,
        context_after,
        paper_guide,
        client.model,
    )
    cached = cache.get(cache_key)
    if cached is not None:
        try:
            validated = validate_translation_response(cached, source_fragment=chunk)
            if validated != cached:
                cache.put(cache_key, validated)
            return path, index, validated
        except DeepSeekError:
            pass

    translated_chunk = client.translate_latex(
        chunk,
        context_before=context_before,
        context_after=context_after,
        paper_guide=paper_guide,
    )
    cache.put(cache_key, translated_chunk)
    return path, index, translated_chunk


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _cache_key(
    fragment: str,
    context_before: str,
    context_after: str,
    paper_guide: str,
    model: str,
) -> str:
    return json.dumps(
        {
            "fragment": fragment,
            "context_before": context_before,
            "context_after": context_after,
            "paper_guide": paper_guide,
            "model": model,
            "preferred_translations": load_preferred_translations(),
            "preserved_terms": load_preserved_terms(),
            "prompt": "latex-guide-context-v5",
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _client_for_chunk(
    path: Path,
    original: str,
    offset: int,
    chunk_length: int,
    main_client: DeepSeekClient,
    appendix_client: DeepSeekClient | None,
    is_appendix_file: bool = False,
) -> DeepSeekClient:
    if appendix_client is None:
        return main_client
    if is_appendix_file or _is_appendix_path(path):
        return appendix_client
    appendix_start = original.find(r"\appendix")
    if appendix_start != -1 and offset + chunk_length > appendix_start:
        return appendix_client
    return main_client


def _appendix_included_paths(root: Path, texts: dict[Path, str]) -> set[Path]:
    appendix_paths: set[Path] = set()
    for path, text in texts.items():
        appendix_start = text.find(r"\appendix")
        if appendix_start == -1:
            continue
        appendix_paths.update(_resolve_inputs(root, path.parent, text[appendix_start:]))
    return appendix_paths


def _resolve_inputs(root: Path, base: Path, text: str) -> set[Path]:
    paths: set[Path] = set()
    for match in re.finditer(r"\\(?:input|include)\s*\{([^{}]+)\}", text):
        name = match.group(1).strip()
        candidates = [base / name, root / name]
        candidates += [path.with_suffix(".tex") for path in candidates if not path.suffix]
        paths.update(path.resolve() for path in candidates if path.exists())
    return paths


def _is_appendix_path(path: Path) -> bool:
    return any(
        "appendix" in part.lower() or "appendices" in part.lower()
        for part in path.parts
    )
