from __future__ import annotations

import unittest

from pdf_to_latex.latex.assemble import assemble_document
from pdf_to_latex.models import PagePlan


class AssemblyTests(unittest.TestCase):
    def test_assembles_pages_and_deduplicates_toc(self) -> None:
        plans = [
            PagePlan(number=1, kind="toc", latex="\\tableofcontents"),
            PagePlan(number=2, kind="toc", latex="\\tableofcontents"),
            PagePlan(number=3, kind="content", latex="Hello"),
        ]
        tex = assemble_document(plans)
        self.assertEqual(tex.count("\\tableofcontents"), 1)
        self.assertIn("% ===== PDF page 3 =====", tex)
        self.assertIn("Hello", tex)
        self.assertTrue(tex.startswith("\\documentclass"))
        self.assertIn("\\end{document}", tex)

    def test_skips_blank_pages(self) -> None:
        plans = [
            PagePlan(number=1, kind="blank"),
            PagePlan(number=2, kind="content", latex="Visible"),
        ]
        tex = assemble_document(plans)
        self.assertNotIn("PDF page 1", tex)
        self.assertIn("PDF page 2", tex)


if __name__ == "__main__":
    unittest.main()
