from __future__ import annotations

from pathlib import Path


def path_uri(path: Path) -> str:
    return path.resolve().as_uri()


def format_path_link(path: Path) -> str:
    resolved = path.resolve()
    return f"{resolved}\n{path_uri(resolved)}"
