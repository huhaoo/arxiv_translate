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
            "-g",
            "-xelatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            str(relative_main),
        ]
        latexmk_returncode = _run(cmd, root, log_path)
        if latexmk_returncode == 0 and output_pdf.exists():
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
        # A source bundle may include a usable .bbl but omit its .bib files.
        # In that case latexmk refuses BibTeX and exits nonzero even though
        # repeated XeLaTeX passes can resolve all citations and references.
        for _ in range(3):
            if _run(cmd, root, log_path) != 0:
                raise CompilationError(
                    "LaTeX compilation failed; see log file:\n"
                    f"{format_path_link(log_path)}"
                )
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


def _run(cmd: list[str], cwd: Path, log_path: Path) -> int:
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
    return proc.returncode
