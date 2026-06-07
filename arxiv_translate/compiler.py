from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .errors import CompilationError
from .links import format_path_link


def compile_latex(root: Path, main_tex: Path) -> Path:
    """Compile the translated paper and return the expected PDF path."""

    relative_main = main_tex.relative_to(root)
    output_pdf = main_tex.with_suffix(".pdf")
    log_path = root / "compile.log"
    log_path.write_text("", encoding="utf-8")

    latexmk = shutil.which("latexmk")
    if latexmk:
        cmd = [
            latexmk,
            "-xelatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            str(relative_main),
        ]
        _run(cmd, root, log_path)
        if output_pdf.exists():
            return output_pdf

    xelatex = shutil.which("xelatex")
    if xelatex:
        cmd = [
            xelatex,
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            str(relative_main),
        ]
        _run(cmd, root, log_path)
        _run(cmd, root, log_path)
        if output_pdf.exists():
            return output_pdf

    if latexmk is None and xelatex is None:
        raise CompilationError(
            "no LaTeX compiler found; install latexmk/xelatex or rerun with --no-compile"
        )
    raise CompilationError(
        "LaTeX compilation did not produce a PDF; see log file:\n"
        f"{format_path_link(log_path)}"
    )


def _run(cmd: list[str], cwd: Path, log_path: Path) -> None:
    with log_path.open("a", encoding="utf-8", errors="replace") as log_file:
        log_file.write(f"$ {' '.join(cmd)}\n")
        log_file.flush()
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=log_file,
            stderr=subprocess.STDOUT,
            check=False,
        )
        log_file.write(f"\n[exit code {proc.returncode}]\n\n")
    if proc.returncode != 0:
        raise CompilationError(
            f"LaTeX compilation failed; see log file:\n{format_path_link(log_path)}"
        )
