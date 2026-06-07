import tempfile
import unittest
from pathlib import Path

from arxiv_translate.links import format_path_link, path_uri


class LinkTests(unittest.TestCase):
    def test_format_path_link_includes_path_and_file_uri(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "compile.log"

            text = format_path_link(path)

            self.assertIn(str(path.resolve()), text)
            self.assertIn(path.resolve().as_uri(), text)
            self.assertEqual(path_uri(path), path.resolve().as_uri())


if __name__ == "__main__":
    unittest.main()
