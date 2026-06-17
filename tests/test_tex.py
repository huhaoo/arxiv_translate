from __future__ import annotations

import unittest

from arxiv_translate.tex import normalize_latex_text_accents


class LatexTextAccentTests(unittest.TestCase):
    def test_normalizes_inline_latex_accents(self) -> None:
        self.assertEqual(
            normalize_latex_text_accents(r"This assumes (na\"ively) caf\'e."),
            "This assumes (naively) cafe.",
        )

    def test_normalizes_braced_latex_accents(self) -> None:
        self.assertEqual(
            normalize_latex_text_accents(r"Garc\'{i}a, Fran\c{c}ois, and Se\~{n}or"),
            "Garcia, Francois, and Senor",
        )

    def test_preserves_verbatim_latex_accents(self) -> None:
        source = "\\begin{verbatim}\nna\\\"ively\n\\end{verbatim}\nna\\\"ively"
        self.assertEqual(
            normalize_latex_text_accents(source),
            "\\begin{verbatim}\nna\\\"ively\n\\end{verbatim}\nnaively",
        )

    def test_does_not_treat_control_words_as_accents(self) -> None:
        source = "\\begin{figure}\n\\caption{caf\\'e}\n\\end{figure}"
        self.assertEqual(
            normalize_latex_text_accents(source),
            "\\begin{figure}\n\\caption{cafe}\n\\end{figure}",
        )


if __name__ == "__main__":
    unittest.main()
