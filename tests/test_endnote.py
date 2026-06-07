import tempfile
import unittest
from pathlib import Path

from arxiv_translate.endnote import format_endnote_import
from arxiv_translate.metadata import ArxivMetadata


class EndNoteTests(unittest.TestCase):
    def test_format_endnote_import(self):
        metadata = ArxivMetadata(
            arxiv_id="2401.12345",
            title="A Short Paper",
            authors=["Ada Lovelace", "Emmy Noether"],
            abstract="An abstract.",
            published="2024-01-01T00:00:00Z",
            updated="2024-01-02T00:00:00Z",
            categories=["math.CO"],
            primary_category="math.CO",
            doi="10.1000/test",
        )
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "original.pdf"
            pdf.write_bytes(b"%PDF")

            text = format_endnote_import(metadata, [pdf])

        self.assertIn("%0 Electronic Article", text)
        self.assertIn("%A Ada Lovelace", text)
        self.assertLess(text.index("%A Ada Lovelace"), text.index("%A Emmy Noether"))
        self.assertIn("%T A Short Paper", text)
        self.assertIn("%R 10.1000/test", text)
        self.assertIn("%> file:///", text)


if __name__ == "__main__":
    unittest.main()
