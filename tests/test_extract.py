import tarfile
import tempfile
import unittest
from pathlib import Path

from arxiv_translate.errors import SourceUnavailableError
from arxiv_translate.extract import extract_source


class ExtractSourceTests(unittest.TestCase):
    def test_extract_tar_with_tex(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_tex = tmp_path / "paper.tex"
            source_tex.write_text("\\documentclass{article}\\begin{document}x\\end{document}")
            archive = tmp_path / "src.tar.gz"
            with tarfile.open(archive, "w:gz") as tf:
                tf.add(source_tex, arcname="paper.tex")

            tex_files = extract_source(archive, tmp_path / "out")

            self.assertEqual([p.name for p in tex_files], ["paper.tex"])

    def test_reject_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / "src.bin"
            archive.write_bytes(b"%PDF-1.4")

            with self.assertRaises(SourceUnavailableError):
                extract_source(archive, tmp_path / "out")


if __name__ == "__main__":
    unittest.main()
