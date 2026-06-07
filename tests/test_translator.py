import tempfile
import time
import unittest
from pathlib import Path

from arxiv_translate.translator import (
    TranslationCache,
    prepare_translated_tree,
    translate_tex_tree,
)


class FakeClient:
    def __init__(self):
        self.calls = []

    def translate_latex(
        self,
        fragment,
        context_before="",
        context_after="",
        paper_guide="",
    ):
        self.calls.append((fragment, context_before, context_after, paper_guide))
        return fragment.upper()


class SlowClient:
    def translate_latex(
        self,
        fragment,
        context_before="",
        context_after="",
        paper_guide="",
    ):
        first_word = fragment.strip().split()[0]
        delays = {"alpha": 0.03, "bravo": 0.01, "charlie": 0}
        time.sleep(delays.get(first_word, 0))
        return f"[{first_word}]"


class TranslatorTests(unittest.TestCase):
    def test_translation_sends_previous_and_next_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            translated = root / "translated"
            source.mkdir()
            (source / "paper.tex").write_text(
                "first paragraph has english text.\n\n"
                "second paragraph has english text.\n\n"
                "third paragraph has english text.",
                encoding="utf-8",
            )
            prepare_translated_tree(source, translated)
            client = FakeClient()
            progress = []

            translate_tex_tree(
                translated,
                client=client,
                cache=TranslationCache(root / "cache.json"),
                chunk_chars=45,
                context_chars=10,
                parallel_chunks=1,
                paper_guide="Use consistent figure terms.",
                progress=lambda done, total, label: progress.append(
                    (done, total, label)
                ),
            )

        self.assertGreaterEqual(len(client.calls), 2)
        self.assertEqual(client.calls[0][1], "")
        self.assertTrue(client.calls[0][2])
        self.assertTrue(client.calls[1][1])
        self.assertEqual(client.calls[0][3], "Use consistent figure terms.")
        self.assertEqual(progress[-1][0], progress[-1][1])
        self.assertEqual(progress[-1][2], "paper.tex")

    def test_parallel_translation_preserves_chunk_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            translated = root / "translated"
            source.mkdir()
            paper = source / "paper.tex"
            paper.write_text(
                "alpha paragraph.\n\n"
                "bravo paragraph.\n\n"
                "charlie paragraph.",
                encoding="utf-8",
            )
            prepare_translated_tree(source, translated)

            translate_tex_tree(
                translated,
                client=SlowClient(),
                cache=TranslationCache(root / "cache.json"),
                chunk_chars=18,
                parallel_chunks=3,
            )

            self.assertEqual(
                (translated / "paper.tex").read_text(encoding="utf-8"),
                "[alpha][bravo][charlie]",
            )


if __name__ == "__main__":
    unittest.main()
