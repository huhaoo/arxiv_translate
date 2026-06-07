import unittest

from arxiv_translate.arxiv import parse_arxiv_id, pdf_url


class ParseArxivIdTests(unittest.TestCase):
    def test_new_abs_url(self):
        self.assertEqual(
            parse_arxiv_id("https://arxiv.org/abs/2401.12345v2"),
            "2401.12345v2",
        )

    def test_pdf_input_url(self):
        self.assertEqual(
            parse_arxiv_id("https://arxiv.org/pdf/2401.12345.pdf"),
            "2401.12345",
        )

    def test_html_url(self):
        self.assertEqual(
            parse_arxiv_id("https://arxiv.org/html/2401.12345"),
            "2401.12345",
        )

    def test_old_style_id(self):
        self.assertEqual(
            parse_arxiv_id("https://arxiv.org/abs/hep-th/9901001v1"),
            "hep-th/9901001v1",
        )

    def test_build_pdf_url(self):
        self.assertEqual(pdf_url("2401.12345"), "https://arxiv.org/pdf/2401.12345")

if __name__ == "__main__":
    unittest.main()
