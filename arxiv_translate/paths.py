from __future__ import annotations

from pathlib import Path

DEFAULT_OUTPUT_DIR = "arxiv_outputs"


def make_job_dir(output_dir: str | Path, arxiv_id: str) -> Path:
    return Path(output_dir).resolve() / safe_arxiv_id(arxiv_id)


def safe_arxiv_id(arxiv_id: str) -> str:
    return arxiv_id.replace("/", "_")
