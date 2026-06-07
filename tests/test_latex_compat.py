import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from arxiv_translate.latex_compat import (
    ensure_chinese_latex_support,
    ensure_latex_compatibility,
    guard_declare_unicode_character_for_xelatex,
    guard_pdfoutput_for_xelatex,
    guard_pdftex_compatibility_for_xelatex,
    replace_bbm_with_dsfont_for_xelatex,
)


class LatexCompatibilityTests(unittest.TestCase):
    def test_guard_pdfoutput_for_xelatex(self):
        text = "\\documentclass{article}\n\\pdfoutput=1\n\\begin{document}x\\end{document}"

        guarded = guard_pdfoutput_for_xelatex(text)

        self.assertIn("\\ifPDFTeX\n\\pdfoutput=1\n\\fi", guarded)

    def test_guard_pdfoutput_is_not_duplicated(self):
        text = (
            "\\documentclass{article}\n"
            "\\ifPDFTeX\n"
            "\\pdfoutput=1\n"
            "\\fi\n"
            "\\begin{document}x\\end{document}"
        )

        guarded = guard_pdfoutput_for_xelatex(text)

        self.assertEqual(guarded, text)

    def test_guard_declare_unicode_character_for_xelatex(self):
        text = (
            "\\documentclass{article}\n"
            "\\DeclareUnicodeCharacter{20AC}{\\EUR{}}\n"
            "\\DeclareUnicodeCharacter{B0}{\\textdegree}\n"
            "\\begin{document}x\\end{document}"
        )

        guarded = guard_declare_unicode_character_for_xelatex(text)

        self.assertIn(
            "\\ifPDFTeX\n"
            "\\DeclareUnicodeCharacter{20AC}{\\EUR{}}\n"
            "\\fi",
            guarded,
        )
        self.assertIn(
            "\\ifPDFTeX\n"
            "\\DeclareUnicodeCharacter{B0}{\\textdegree}\n"
            "\\fi",
            guarded,
        )

    def test_guard_declare_unicode_character_is_not_duplicated(self):
        text = (
            "\\documentclass{article}\n"
            "\\ifPDFTeX\n"
            "\\DeclareUnicodeCharacter{20AC}{\\EUR{}}\n"
            "\\fi\n"
            "\\begin{document}x\\end{document}"
        )

        guarded = guard_declare_unicode_character_for_xelatex(text)

        self.assertEqual(guarded, text)

    def test_guard_pdftex_compatibility_handles_common_pdftex_commands(self):
        text = (
            "\\documentclass{article}\n"
            "\\pdfoutput=1\n"
            "\\usepackage{bbm}\n"
            "\\DeclareUnicodeCharacter{20AC}{\\EUR{}}\n"
            "\\begin{document}$\\mathbbm{1}$\\end{document}"
        )

        guarded = guard_pdftex_compatibility_for_xelatex(text)

        self.assertEqual(guarded.count("\\ifPDFTeX"), 2)
        self.assertIn("\\pdfoutput=1", guarded)
        self.assertIn("\\DeclareUnicodeCharacter{20AC}{\\EUR{}}", guarded)
        self.assertIn("\\usepackage{dsfont}", guarded)
        self.assertIn("\\mathds{1}", guarded)

    def test_replace_bbm_with_dsfont_for_xelatex(self):
        text = (
            "\\documentclass{article}\n"
            "\\usepackage{bbm} % double stroke\n"
            "\\begin{document}$\\mathbbm{1}$\\end{document}"
        )

        fixed = replace_bbm_with_dsfont_for_xelatex(text)

        self.assertIn("\\usepackage{dsfont} % double stroke", fixed)
        self.assertIn("\\mathds{1}", fixed)
        self.assertNotIn("\\usepackage{bbm}", fixed)
        self.assertNotIn("\\mathbbm", fixed)

    def test_ensure_chinese_latex_support_guards_pdfoutput_even_with_ctex(self):
        with TemporaryDirectory() as tmp:
            main_tex = Path(tmp) / "main.tex"
            main_tex.write_text(
                "\\documentclass{article}\n"
                "\\usepackage{ctex}\n"
                "\\pdfoutput=1\n"
                "\\begin{document}Chinese text\\end{document}",
                encoding="utf-8",
            )

            changed = ensure_chinese_latex_support(main_tex)

            self.assertTrue(changed)
            text = main_tex.read_text(encoding="utf-8")
            self.assertIn("\\ifPDFTeX\n\\pdfoutput=1\n\\fi", text)
            self.assertIn("\\usepackage{iftex}", text)
            self.assertEqual(text.count("\\usepackage{ctex}"), 1)

    def test_ensure_chinese_latex_support_guards_unicode_declarations(self):
        with TemporaryDirectory() as tmp:
            main_tex = Path(tmp) / "main.tex"
            main_tex.write_text(
                "\\documentclass{article}\n"
                "\\usepackage{ctex}\n"
                "\\usepackage{bbm}\n"
                "\\DeclareUnicodeCharacter{20AC}{\\EUR{}}\n"
                "\\begin{document}$\\mathbbm{1}$\\end{document}",
                encoding="utf-8",
            )

            changed = ensure_chinese_latex_support(main_tex)

            self.assertTrue(changed)
            text = main_tex.read_text(encoding="utf-8")
            self.assertIn("\\usepackage{iftex}", text)
            self.assertIn(
                "\\ifPDFTeX\n\\DeclareUnicodeCharacter{20AC}{\\EUR{}}\n\\fi",
                text,
            )
            self.assertIn("\\usepackage{dsfont}", text)
            self.assertIn("\\mathds{1}", text)

    def test_ensure_latex_compatibility_fixes_included_files(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            sections = root / "sections"
            sections.mkdir()
            main_tex = root / "root.tex"
            child_tex = sections / "appendix.tex"
            main_tex.write_text(
                "\\documentclass{article}\n"
                "\\pdfoutput=1\n"
                "\\usepackage{bbm}\n"
                "\\DeclareUnicodeCharacter{20AC}{\\EUR{}}\n"
                "\\begin{document}\\input{sections/appendix}\\end{document}",
                encoding="utf-8",
            )
            child_tex.write_text("$\\mathbbm{1}$", encoding="utf-8")

            changed = ensure_latex_compatibility(root)

            self.assertEqual(set(changed), {main_tex, child_tex})
            self.assertIn("\\usepackage{dsfont}", main_tex.read_text(encoding="utf-8"))
            self.assertIn("\\mathds{1}", child_tex.read_text(encoding="utf-8"))

    def test_ensure_latex_compatibility_finishes_partial_bbm_fix(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            sections = root / "sections"
            sections.mkdir()
            main_tex = root / "root.tex"
            child_tex = sections / "appendix.tex"
            main_tex.write_text(
                "\\documentclass{article}\n"
                "\\usepackage{dsfont}\n"
                "\\begin{document}\\input{sections/appendix}\\end{document}",
                encoding="utf-8",
            )
            child_tex.write_text("$\\mathbbm{1}$", encoding="utf-8")

            changed = ensure_latex_compatibility(root)

            self.assertEqual(changed, [child_tex])
            self.assertIn("\\mathds{1}", child_tex.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
