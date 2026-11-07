from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pdf_to_latex.config import Settings
from pdf_to_latex.ocr.cache import ResponseCache
from pdf_to_latex.ocr.client import DeepSeekClient


class TruncationTests(unittest.TestCase):
    def _client(self, root: Path, *, max_tokens: int, cap: int) -> DeepSeekClient:
        settings = Settings(
            pdf=root / "input.pdf",
            output=root / "output.tex",
            workdir=root / "work",
            max_tokens=max_tokens,
            max_tokens_cap=cap,
            skip_model_check=True,
        )
        return DeepSeekClient(settings, ResponseCache(root / "cache", enabled=False))

    @staticmethod
    def _response(content: str, finish_reason: str) -> dict:
        return {
            "choices": [
                {
                    "message": {"content": content},
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {"completion_tokens": 10},
            "model": "deepseek-flash",
        }

    def test_retries_truncated_content_with_a_larger_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "page.jpg"
            image.write_bytes(b"not-a-real-jpeg")
            responses = [
                self._response("partial", "length"),
                self._response("complete", "stop"),
            ]
            with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test"}):
                client = self._client(root, max_tokens=100, cap=400)
                with mock.patch.object(
                    client, "_post_json", side_effect=responses
                ) as post:
                    result = client.transcribe(
                        image_path=image,
                        page_text="",
                        page_number=1,
                        total_pages=1,
                    )

            self.assertEqual(result.latex, "complete")
            self.assertEqual(result.finish_reason, "stop")
            self.assertEqual(post.call_count, 2)
            budgets = [call.args[1]["max_tokens"] for call in post.call_args_list]
            self.assertEqual(budgets, [100, 200])

    def test_returns_partial_content_at_cap_instead_of_failing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "page.jpg"
            image.write_bytes(b"not-a-real-jpeg")
            with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test"}):
                client = self._client(root, max_tokens=100, cap=100)
                with mock.patch.object(
                    client,
                    "_post_json",
                    side_effect=[self._response("partial", "length")],
                ) as post:
                    result = client.transcribe(
                        image_path=image,
                        page_text="",
                        page_number=1,
                        total_pages=1,
                    )

            self.assertEqual(result.latex, "partial")
            self.assertEqual(result.finish_reason, "length")
            self.assertEqual(post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
