import tempfile
import unittest
from pathlib import Path

from arxiv_translate.paths import DEFAULT_OUTPUT_DIR, make_job_dir, safe_arxiv_id


class PathTests(unittest.TestCase):
    def test_default_output_dir(self):
        self.assertEqual(DEFAULT_OUTPUT_DIR, "arxiv_outputs")

    def test_safe_arxiv_id(self):
        self.assertEqual(safe_arxiv_id("hep-th/9901001v1"), "hep-th_9901001v1")

    def test_make_job_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_job_dir(tmp, "2401.12345")
            self.assertEqual(
                path,
                Path(tmp).resolve() / "2401.12345",
            )


if __name__ == "__main__":
    unittest.main()
