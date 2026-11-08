from __future__ import annotations

import unittest

from pdf_to_latex.ocr.prompts import build_prompt


class PromptTests(unittest.TestCase):
    def _prompt(self, *, include_figures: bool) -> str:
        return build_prompt(
            page_text="Some text.",
            page_number=3,
            total_pages=10,
            include_figures=include_figures,
        )

    def test_figure_rules_describe_the_box_protocol(self) -> None:
        prompt = self._prompt(include_figures=True)
        self.assertIn("% FIG-BOX <n>: x0,y0,x1,y1", prompt)
        self.assertIn("\\includegraphics[width=0.8\\linewidth]{FIG:<n>}", prompt)
        self.assertIn("top-left corner", prompt)

    def test_figure_rules_forbid_redrawing(self) -> None:
        prompt = self._prompt(include_figures=True)
        self.assertIn("Do not redraw", prompt)
        self.assertNotIn("Do not use \\includegraphics", prompt)

    def test_disabling_figures_removes_the_protocol(self) -> None:
        prompt = self._prompt(include_figures=False)
        self.assertNotIn("FIG-BOX", prompt)
        self.assertIn("Do not use \\includegraphics", prompt)

    def test_page_context_is_preserved(self) -> None:
        prompt = self._prompt(include_figures=True)
        self.assertIn("PDF page 3 of 10", prompt)


if __name__ == "__main__":
    unittest.main()
