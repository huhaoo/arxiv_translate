import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from arxiv_translate.cli import (
    TRANSLATED_PDF_NAME,
    _append_interactive_history,
    _is_completed_job,
    _normalize_translated_pdf,
)
from arxiv_translate.cli import build_parser, main, run
from arxiv_translate.errors import SourceUnavailableError
from arxiv_translate.metadata import ArxivMetadata


class CliTests(unittest.TestCase):
    def test_parallel_chunks_defaults_to_four(self):
        args = build_parser().parse_args(["2401.12345"])

        self.assertEqual(args.parallel_chunks, 4)
        self.assertFalse(args.redo)

    def test_redo_flag(self):
        args = build_parser().parse_args(["2401.12345", "--redo"])

        self.assertTrue(args.redo)

    def test_missing_link_enters_interactive_mode(self):
        with mock.patch("builtins.input", side_effect=["exit"]):
            with redirect_stdout(io.StringIO()) as output:
                exit_code = main([])

        self.assertEqual(exit_code, 0)
        self.assertIn("Interactive mode", output.getvalue())

    def test_no_tex_source_still_writes_endnote(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config.local.json"
            config.write_text(
                """{
  "deepseek_api_key": "sk-test",
  "deepseek_model": "deepseek-v4-pro",
  "deepseek_guide_model": "deepseek-v4-flash",
  "deepseek_base_url": "https://api.deepseek.com/chat/completions"
}""",
                encoding="utf-8",
            )
            args = build_parser().parse_args(
                [
                    "https://arxiv.org/abs/2401.12345",
                    "--config",
                    str(config),
                    "--output-dir",
                    str(root / "out"),
                ]
            )
            metadata = ArxivMetadata(
                arxiv_id="2401.12345",
                title="PDF Only Paper",
                authors=["Ada Lovelace"],
                abstract="No TeX source.",
                published="2024-01-01T00:00:00Z",
                updated="2024-01-01T00:00:00Z",
                categories=["math.CO"],
            )

            def write_pdf(_arxiv_id, destination):
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"%PDF")
                return destination

            with (
                mock.patch("arxiv_translate.cli.fetch_arxiv_metadata", return_value=metadata),
                mock.patch("arxiv_translate.cli.download_pdf", side_effect=write_pdf),
                mock.patch(
                    "arxiv_translate.cli.download_source",
                    side_effect=SourceUnavailableError("no TeX source"),
                ),
            ):
                with redirect_stdout(io.StringIO()):
                    exit_code = run(args)

            job_dir = root / "out" / "2401.12345"
            self.assertEqual(exit_code, 0)
            self.assertTrue((job_dir / "original.pdf").exists())
            self.assertTrue((job_dir / "endnote.enw").exists())
            endnote = (job_dir / "endnote.enw").read_text(encoding="utf-8-sig")
            self.assertIn("%T PDF Only Paper", endnote)
            self.assertIn("%> file:///", endnote)

    def test_completed_job_skips_before_config_or_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job_dir = root / "out" / "2401.12345"
            translated_dir = job_dir / "translated"
            translated_dir.mkdir(parents=True)
            (job_dir / "original.pdf").write_bytes(b"%PDF")
            (job_dir / "endnote.enw").write_text("%T Done\n", encoding="utf-8")
            (translated_dir / TRANSLATED_PDF_NAME).write_bytes(b"%PDF")
            args = build_parser().parse_args(
                [
                    "https://arxiv.org/abs/2401.12345",
                    "--config",
                    str(root / "missing-config.json"),
                    "--output-dir",
                    str(root / "out"),
                ]
            )

            with mock.patch(
                "arxiv_translate.cli.fetch_arxiv_metadata",
                side_effect=AssertionError("network should not be called"),
            ):
                with redirect_stdout(io.StringIO()) as output:
                    exit_code = run(args)

            self.assertEqual(exit_code, 0)
            self.assertIn("existing completed output", output.getvalue())
            self.assertIn(job_dir.resolve().as_uri(), output.getvalue())

    def test_completed_job_helper_for_pdf_and_source_unavailable_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            full_job = root / "full"
            (full_job / "translated").mkdir(parents=True)
            (full_job / "original.pdf").write_bytes(b"%PDF")
            (full_job / "endnote.enw").write_text("%T Done\n", encoding="utf-8")
            (full_job / "translated" / TRANSLATED_PDF_NAME).write_bytes(b"%PDF")

            no_tex_job = root / "no-tex"
            (no_tex_job / "source").mkdir(parents=True)
            (no_tex_job / "original.pdf").write_bytes(b"%PDF")
            (no_tex_job / "endnote.enw").write_text("%T Done\n", encoding="utf-8")

            incomplete_job = root / "incomplete"
            (incomplete_job / "source").mkdir(parents=True)
            (incomplete_job / "original.pdf").write_bytes(b"%PDF")
            (incomplete_job / "endnote.enw").write_text("%T Done\n", encoding="utf-8")
            (incomplete_job / "source" / "paper.tex").write_text(
                "\\begin{document}Hi\\end{document}",
                encoding="utf-8",
            )

            self.assertTrue(_is_completed_job(full_job))
            self.assertTrue(_is_completed_job(no_tex_job))
            self.assertFalse(_is_completed_job(incomplete_job))

    def test_normalize_translated_pdf_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            translated_dir = Path(tmp) / "translated"
            translated_dir.mkdir()
            compiled_pdf = translated_dir / "paper.pdf"
            compiled_pdf.write_bytes(b"%PDF")

            normalized = _normalize_translated_pdf(compiled_pdf, translated_dir)

            self.assertEqual(normalized, translated_dir / TRANSLATED_PDF_NAME)
            self.assertTrue(normalized.exists())
            self.assertFalse(compiled_pdf.exists())

    def test_append_interactive_history_persists_unique_recent_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = Path(tmp) / "history.txt"
            history = []

            _append_interactive_history(history, "2401.1", history_path)
            _append_interactive_history(history, "2401.1", history_path)
            _append_interactive_history(history, "2401.2", history_path)

            self.assertEqual(history, ["2401.1", "2401.2"])
            self.assertEqual(
                history_path.read_text(encoding="utf-8").splitlines(),
                ["2401.1", "2401.2"],
            )


if __name__ == "__main__":
    unittest.main()
