import tempfile
import unittest
from pathlib import Path

from arxiv_translate.guide import collect_latex_document, load_or_generate_paper_guide


class FakeGuideClient:
    def __init__(self):
        self.calls = []

    def generate_paper_guide(self, latex_document):
        self.calls.append(latex_document)
        return "# Paper Translation Guide\n\n## Glossary\n"


class GuideTests(unittest.TestCase):
    def test_collect_latex_document_marks_file_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text("\\section{Intro}", encoding="utf-8")

            document = collect_latex_document(root)

        self.assertIn('<LATEX_FILE path="main.tex">', document)
        self.assertIn("\\section{Intro}", document)

    def test_load_or_generate_paper_guide_uses_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.tex").write_text("\\section{Intro}", encoding="utf-8")
            guide_path = root / "paper-guide.md"
            client = FakeGuideClient()

            guide = load_or_generate_paper_guide(source, guide_path, client)
            cached = load_or_generate_paper_guide(source, guide_path, client)

        self.assertEqual(guide, cached)
        self.assertEqual(len(client.calls), 1)


if __name__ == "__main__":
    unittest.main()
