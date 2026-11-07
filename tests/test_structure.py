from __future__ import annotations

import unittest

from pdf_to_latex.validate.structure import (
    count_pdf_headings,
    count_tex_headings,
    validate_structure,
)
from pdf_to_latex.models import PagePlan


class StructureTests(unittest.TestCase):
    def test_counts_headings(self) -> None:
        pdf_text = """
Theorem 1.1. Let X.
Definition 1.2. Let Y.
Remark 1.1. A remark.
Exercise 1.1. Do this.
"""
        self.assertEqual(count_pdf_headings(pdf_text)["theorem"], 1)
        self.assertEqual(count_pdf_headings(pdf_text)["definition"], 1)
        self.assertEqual(count_pdf_headings(pdf_text)["remark"], 1)
        self.assertEqual(count_pdf_headings(pdf_text)["exercise"], 1)

        tex = r"""
\begin{theorem}
X
\end{theorem}
\begin{definition}
Y
\end{definition}
"""
        self.assertEqual(count_tex_headings(tex)["theorem"], 1)
        self.assertEqual(count_tex_headings(tex)["definition"], 1)

    def test_reports_missing_headings_and_fragments(self) -> None:
        pdf_text = "Theorem 1.1. X\nTheorem 1.2. Y\n"
        tex = r"\begin{theorem}X\end{theorem}"
        plans = [PagePlan(number=1, kind="content", text="Theorem 1.1")]
        result = validate_structure(pdf_text, tex, plans)
        self.assertEqual(result["missing_headings"]["theorem"], 1)
        self.assertEqual(result["missing_fragments"], [1])


if __name__ == "__main__":
    unittest.main()
