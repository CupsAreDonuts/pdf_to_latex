from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

from pdf_to_latex.config import Settings
from pdf_to_latex.exceptions import ConfigError
from pdf_to_latex.models import OcrResult
from pdf_to_latex.ocr.client import DeepSeekClient
from pdf_to_latex.pipeline import Pipeline


def _make_pdf(root: Path) -> Path:
    """A one-page image-only PDF with a black rectangle in the upper half."""
    image = Image.new("RGB", (1200, 1600), "white")
    ImageDraw.Draw(image).rectangle((200, 400, 900, 1000), fill="black")
    pdf = root / "input.pdf"
    image.save(pdf, format="PDF", resolution=100)
    return pdf


def _settings(root: Path, *, output: str = "book") -> Settings:
    return Settings(
        pdf=root / "input.pdf",
        output=root / output,
        workdir=root / "work",
        workers=1,
        dpi=100,
        figure_dpi=150,
        skip_model_check=True,
    )


def _ocr(latex: str) -> OcrResult:
    return OcrResult(
        latex=latex, reasoning=None, usage={}, finish_reason="stop"
    )


FIGURE_FRAGMENT = (
    "% FIG-BOX 1: 167,250,750,625\n"
    "\\section{A figure page}\n"
    "\\begin{figure}[htbp]\n"
    "\\centering\n"
    "\\includegraphics[width=0.8\\linewidth]{FIG:1}\n"
    "\\caption{A black rectangle.}\n"
    "\\end{figure}\n"
)


class PipelineFigureIntegrationTests(unittest.TestCase):
    def _run(self, root: Path, latex: str, *, output: str = "book") -> int:
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test"}):
            with mock.patch.object(DeepSeekClient, "check_model"):
                with mock.patch.object(
                    DeepSeekClient,
                    "transcribe",
                    return_value=_ocr(latex),
                ):
                    return Pipeline(_settings(root, output=output)).run()

    def test_cropped_figure_is_delivered_in_a_compiling_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_pdf(root)
            exit_code = self._run(root, FIGURE_FRAGMENT)

            self.assertEqual(exit_code, 0)
            tex = (root / "book" / "book.tex").read_text(encoding="utf-8")
            self.assertIn("figures/book/p0001-f01.png", tex)
            self.assertNotIn("FIG-BOX", tex)
            self.assertNotIn("{FIG:1}", tex)
            self.assertTrue((root / "book" / "book.pdf").exists())
            self.assertTrue(
                (root / "book" / "figures" / "book" / "p0001-f01.png").exists()
            )
            report = json.loads(
                (root / "work" / "report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(report["usage"]["figures"], 1)

    def test_pages_without_ocr_text_fall_back_to_the_whole_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_pdf(root)
            exit_code = self._run(root, "")

            self.assertEqual(exit_code, 0)
            tex = (root / "book" / "book.tex").read_text(encoding="utf-8")
            self.assertIn("figures/book/p0001-page.png", tex)
            self.assertTrue(
                (root / "book" / "figures" / "book" / "p0001-page.png").exists()
            )

    def test_contentless_fragment_falls_back_to_the_page_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_pdf(root)
            exit_code = self._run(root, "% no visible content\n\\clearpage\n")

            self.assertEqual(exit_code, 0)
            tex = (root / "book" / "book.tex").read_text(encoding="utf-8")
            self.assertIn("figures/book/p0001-page.png", tex)

    def test_shared_workdir_does_not_leak_figures_between_bundles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_pdf(root)
            self.assertEqual(self._run(root, FIGURE_FRAGMENT, output="book"), 0)
            self.assertEqual(self._run(root, FIGURE_FRAGMENT, output="other"), 0)

            self.assertTrue(
                (root / "book" / "figures" / "book" / "p0001-f01.png").exists()
            )
            self.assertFalse((root / "book" / "figures" / "other").exists())
            self.assertTrue(
                (root / "other" / "figures" / "other" / "p0001-f01.png").exists()
            )

    def test_refuses_to_overwrite_the_input_pdf_with_the_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / "book"
            bundle.mkdir()
            image = Image.new("RGB", (400, 500), "white")
            input_pdf = bundle / "book.pdf"
            image.save(input_pdf, format="PDF", resolution=100)
            settings = Settings(
                pdf=input_pdf,
                output=bundle,
                workdir=root / "work",
                skip_model_check=True,
            )
            with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test"}):
                with self.assertRaises(ConfigError):
                    Pipeline(settings).run()


if __name__ == "__main__":
    unittest.main()
