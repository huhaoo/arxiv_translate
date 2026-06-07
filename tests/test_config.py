import tempfile
import unittest
from pathlib import Path

from arxiv_translate.config import config_string, load_config
from arxiv_translate.errors import ArxivTranslateError


class ConfigTests(unittest.TestCase):
    def test_load_missing_config(self):
        with self.assertRaises(ArxivTranslateError):
            load_config("missing-config.json")

    def test_load_json_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.local.json"
            path.write_text('{"deepseek_api_key": "sk-test"}', encoding="utf-8")

            self.assertEqual(load_config(path)["deepseek_api_key"], "sk-test")

    def test_reject_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.local.json"
            path.write_text("{", encoding="utf-8")

            with self.assertRaises(ArxivTranslateError):
                load_config(path)

    def test_config_string(self):
        self.assertEqual(
            config_string({"deepseek_model": "from-config"}, "deepseek_model"),
            "from-config",
        )
        with self.assertRaises(ArxivTranslateError):
            config_string({}, "deepseek_model")


if __name__ == "__main__":
    unittest.main()
