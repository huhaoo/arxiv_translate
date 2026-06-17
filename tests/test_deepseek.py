from __future__ import annotations

import unittest

from arxiv_translate.deepseek import (
    validate_translation_protocol,
    validate_translation_response,
)
from arxiv_translate.errors import DeepSeekError


class TranslationProtocolTests(unittest.TestCase):
    def test_rejects_prompt_marker_converted_to_latex_environment(self) -> None:
        with self.assertRaises(DeepSeekError):
            validate_translation_protocol(r"\end{CURRENT_FRAGMENT}translated text")

    def test_rejects_latex_backtick_quote_punctuation(self) -> None:
        with self.assertRaises(DeepSeekError):
            validate_translation_protocol('一个``折衷""预测')

    def test_rejects_escaped_latex_quote_punctuation(self) -> None:
        with self.assertRaises(DeepSeekError):
            validate_translation_protocol(r"一个\`\`折衷''预测")

    def test_normalizes_latex_quote_punctuation_before_validation(self) -> None:
        self.assertEqual(
            validate_translation_response("Ends with the word ``press''"),
            'Ends with the word "press"',
        )

    def test_normalizes_single_backtick_before_validation(self) -> None:
        self.assertEqual(
            validate_translation_response("word `press"),
            "word ’press",
        )

    def test_normalizes_escaped_latex_quote_punctuation_before_validation(self) -> None:
        self.assertEqual(
            validate_translation_response(r"一个\`\`折衷''预测"),
            '一个"折衷"预测',
        )

    def test_accepts_plain_ascii_double_quotes(self) -> None:
        validate_translation_protocol('一个"折衷"预测')

    def test_accepts_right_single_quote(self) -> None:
        validate_translation_protocol("一种’否决’机制")


if __name__ == "__main__":
    unittest.main()
