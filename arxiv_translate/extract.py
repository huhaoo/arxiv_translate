from __future__ import annotations

import gzip
import shutil
import tarfile
import zipfile
from io import BytesIO
from pathlib import Path

from .errors import SourceUnavailableError

TEX_SUFFIXES = {".tex", ".ltx"}


def extract_source(archive_path: Path, output_dir: Path) -> list[Path]:
    """Extract an arXiv source package and return discovered TeX files."""

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw = archive_path.read_bytes()
    if raw.startswith(b"%PDF"):
        raise SourceUnavailableError("downloaded source is a PDF, not TeX source")

    if _extract_tar(archive_path, output_dir) or _extract_zip(archive_path, output_dir):
        return _require_tex_files(output_dir)

    if _looks_gzip(raw):
        inflated = gzip.decompress(raw)
        if _extract_tar_bytes(inflated, output_dir):
            return _require_tex_files(output_dir)
        _write_single_source(inflated, output_dir)
        return _require_tex_files(output_dir)

    _write_single_source(raw, output_dir)
    return _require_tex_files(output_dir)


def _extract_tar(archive_path: Path, output_dir: Path) -> bool:
    try:
        with tarfile.open(archive_path, mode="r:*") as tf:
            _extract_tar_safely(tf, output_dir)
        return True
    except tarfile.TarError:
        return False


def _extract_tar_bytes(raw: bytes, output_dir: Path) -> bool:
    try:
        with tarfile.open(fileobj=BytesIO(raw), mode="r:*") as tf:
            _extract_tar_safely(tf, output_dir)
        return True
    except tarfile.TarError:
        return False


def _extract_zip(archive_path: Path, output_dir: Path) -> bool:
    if not zipfile.is_zipfile(archive_path):
        return False
    with zipfile.ZipFile(archive_path) as zf:
        for member in zf.infolist():
            if member.is_dir():
                _safe_target(output_dir, member.filename).mkdir(parents=True, exist_ok=True)
                continue
            with zf.open(member) as src:
                _copy_member(src, output_dir, member.filename)
    return True


def _extract_tar_safely(tf: tarfile.TarFile, output_dir: Path) -> None:
    for member in tf.getmembers():
        if member.isdir():
            _safe_target(output_dir, member.name).mkdir(parents=True, exist_ok=True)
            continue
        if not member.isfile():
            continue
        source = tf.extractfile(member)
        if source is not None:
            with source:
                _copy_member(source, output_dir, member.name)


def _copy_member(source, output_dir: Path, member_name: str) -> None:
    target = _safe_target(output_dir, member_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as dst:
        shutil.copyfileobj(source, dst)


def _safe_target(root: Path, member_name: str) -> Path:
    target = (root / member_name).resolve()
    root_resolved = root.resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise SourceUnavailableError(f"unsafe path in source archive: {member_name}")
    return target


def _looks_gzip(raw: bytes) -> bool:
    return len(raw) >= 2 and raw[:2] == b"\x1f\x8b"


def _write_single_source(raw: bytes, output_dir: Path) -> None:
    if not _looks_like_tex(raw):
        raise SourceUnavailableError("downloaded source archive does not contain TeX")
    (output_dir / "main.tex").write_bytes(raw)


def _looks_like_tex(raw: bytes) -> bool:
    head = raw[:4096].decode("utf-8", errors="ignore")
    return "\\documentclass" in head or "\\begin{document}" in head or "\\input" in head


def _require_tex_files(output_dir: Path) -> list[Path]:
    tex_files = [
        path
        for path in output_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in TEX_SUFFIXES
    ]
    if not tex_files:
        raise SourceUnavailableError("arXiv source package contains no .tex/.ltx files")
    return sorted(tex_files)
