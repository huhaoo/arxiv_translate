import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from arxiv_translate.compiler import compile_latex
from arxiv_translate.errors import CompilationError


class CompilerTests(unittest.TestCase):
    def test_latex_failure_writes_log_and_reports_only_log_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main_tex = root / "paper.tex"
            main_tex.write_text("\\begin{document}\\bad\\end{document}", encoding="utf-8")
            log_path = root / "compile.log"

            def fake_run(*_args, stdout=None, **_kwargs):
                stdout.write("very noisy LaTeX failure details\n")
                return SimpleNamespace(returncode=1)

            with (
                mock.patch(
                    "arxiv_translate.compiler.shutil.which",
                    side_effect=lambda name: None if name == "latexmk" else "xelatex",
                ),
                mock.patch("arxiv_translate.compiler.subprocess.run", side_effect=fake_run),
            ):
                with self.assertRaises(CompilationError) as raised:
                    compile_latex(root, main_tex)

            self.assertTrue(log_path.exists())
            self.assertIn("very noisy LaTeX failure details", log_path.read_text())
            message = str(raised.exception)
            self.assertIn(str(log_path.resolve()), message)
            self.assertIn(log_path.resolve().as_uri(), message)
            self.assertNotIn("very noisy LaTeX failure details", message)


if __name__ == "__main__":
    unittest.main()
