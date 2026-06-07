import unittest

from arxiv_translate.tex import _is_safe_latex_boundary, split_latex_for_translation


class TexSplitTests(unittest.TestCase):
    def test_split_does_not_break_brace_group_across_blank_line(self):
        text = "before\n\n\\cmd{{alpha}\n\nbeta}\n\nafter"

        chunks = split_latex_for_translation(text, max_chars=22)

        self.assertIn("\\cmd{{alpha}\n\nbeta}", "".join(chunks))
        self.assertFalse(any(chunk.endswith("\\cmd{{alpha}\n\n") for chunk in chunks))
        self.assertTrue(all(_is_safe_latex_boundary(chunk) for chunk in chunks))

    def test_split_does_not_break_long_paragraph(self):
        text = "before $a + b + c + d + e + f$ after"

        chunks = split_latex_for_translation(text, max_chars=12)

        self.assertEqual(chunks, [text])

    def test_boundary_ignores_escaped_braces(self):
        self.assertTrue(_is_safe_latex_boundary(r"\{ literal \}"))

    def test_boundary_rejects_unclosed_brace(self):
        self.assertFalse(_is_safe_latex_boundary(r"\textbf{open"))

    def test_math_interval_brackets_do_not_block_split(self):
        self.assertTrue(_is_safe_latex_boundary(r"$\phi:[0,1]\to[0,\infty)$"))

    def test_split_does_not_break_latex_environment_or_long_paragraphs(self):
        text = (
            "\\begin{proof}\n"
            "This is a long proof paragraph with enough words to exceed the limit.\n\n"
            "This is the second proof paragraph.\n"
            "\\end{proof}\n"
            "after"
        )

        chunks = split_latex_for_translation(text, max_chars=45)

        self.assertEqual(chunks, [text])
        self.assertTrue(all(_is_safe_latex_boundary(chunk) for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
