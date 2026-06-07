import unittest

from arxiv_translate.deepseek import (
    DeepSeekClient,
    _guide_request,
    _remove_markdown_fence,
    _retry_delay,
    _translation_request,
)
from arxiv_translate.errors import DeepSeekError


class DeepSeekSanitizeTests(unittest.TestCase):
    def test_preserves_plain_whitespace(self):
        self.assertEqual(_remove_markdown_fence("\nhello\n"), "\nhello\n")

    def test_removes_markdown_fence(self):
        self.assertEqual(_remove_markdown_fence("```latex\nhello\n```"), "hello")

    def test_translation_request_marks_context_as_reference_only(self):
        request = _translation_request(
            "Current sentence.",
            context_before="Previous sentence.",
            context_after="Next sentence.",
            paper_guide="Use 图同态 for graph homomorphism.",
        )

        self.assertIn("<PAPER_TRANSLATION_GUIDE>", request)
        self.assertIn("Use 图同态", request)
        self.assertIn("<PREVIOUS_CONTEXT>", request)
        self.assertIn("<CURRENT_FRAGMENT>", request)
        self.assertIn("<NEXT_CONTEXT>", request)
        self.assertIn("Do not translate them", request)
        self.assertIn("do not repeat", request)
        self.assertIn("Return only", request)

    def test_guide_request_has_fixed_sections_and_full_source(self):
        request = _guide_request("\\section{Intro}")

        self.assertIn("# Paper Translation Guide", request)
        self.assertIn("## Glossary", request)
        self.assertIn("<COMPLETE_LATEX_SOURCE>", request)
        self.assertIn("\\section{Intro}", request)

    def test_model_and_base_url_are_explicit(self):
        client = DeepSeekClient(
            api_key="sk-test",
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com/chat/completions",
        )

        self.assertEqual(client.model, "deepseek-v4-pro")

    def test_rate_limit_retry_delay(self):
        exc = DeepSeekError("rate limited", status_code=429, retryable=True)
        self.assertEqual(_retry_delay(exc, 1), 5)
        self.assertEqual(_retry_delay(exc, 10), 30)

    def test_non_retryable_error_stops_immediately(self):
        calls = []

        class FailingClient(DeepSeekClient):
            def _post(self, payload):
                calls.append(payload)
                raise DeepSeekError("bad request", status_code=400, retryable=False)

        with self.assertRaises(DeepSeekError):
            FailingClient(
                api_key="sk-test",
                model="deepseek-v4-pro",
                base_url="https://api.deepseek.com/chat/completions",
                retries=3,
            ).translate_latex("hello")

        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
