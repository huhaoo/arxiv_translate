from __future__ import annotations

import hashlib
import json
import shutil
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .deepseek import DeepSeekClient
from .tex import should_translate_tex, split_latex_for_translation


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
    chunk_chars: int = 4096,
    context_chars: int = 500,
    parallel_chunks: int = 4,
    paper_guide: str = "",
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

    jobs: list[tuple[Path, str, list[str]]] = []
    for path in tex_files:
        original = path.read_text(encoding="utf-8", errors="ignore")
        if not should_translate_tex(original):
            continue

        chunks = split_latex_for_translation(original, chunk_chars)
        if chunks:
            jobs.append((path, original, chunks))

    done_chunks = 0
    total_chunks = sum(len(chunks) for _, _, chunks in jobs)
    outputs: dict[Path, list[str | None]] = {
        path: [None] * len(chunks) for path, _, chunks in jobs
    }
    work_items: list[tuple[Path, int, str, str, str]] = []

    for path, original, chunks in jobs:
        offset = 0
        for index, chunk in enumerate(chunks):
            context_before = original[max(0, offset - context_chars) : offset]
            context_after_start = offset + len(chunk)
            context_after = original[
                context_after_start : context_after_start + context_chars
            ]
            work_items.append(
                (path, index, chunk, context_before, context_after)
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
                client,
                cache,
            )
            for path, index, chunk, context_before, context_after in work_items
        ]
        for future in as_completed(futures):
            path, index, translated_chunk = future.result()
            outputs[path][index] = translated_chunk
            done_chunks += 1
            if progress is not None:
                progress(done_chunks, total_chunks, path.name)

    for path, _, _ in jobs:
        out = outputs[path]
        path.write_text("".join(part or "" for part in out), encoding="utf-8", newline="")
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
    cache_key = _cache_key(chunk, context_before, context_after, paper_guide)
    cached = cache.get(cache_key)
    if cached is not None:
        return path, index, cached

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
) -> str:
    return json.dumps(
        {
            "fragment": fragment,
            "context_before": context_before,
            "context_after": context_after,
            "paper_guide": paper_guide,
            "prompt": "latex-guide-context-v1",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
