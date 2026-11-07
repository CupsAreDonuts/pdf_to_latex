from __future__ import annotations

import unittest

from pdf_to_latex.ocr.sanitize import (
    content_words,
    extract_uncertain,
    latex_to_plain_text,
    sanitize_latex,
)


class SanitizeTests(unittest.TestCase):
    def test_removes_code_fence_and_document_wrapper(self) -> None:
        raw = r"""```latex
\documentclass{book}
\usepackage{amsmath}
\begin{document}
Hello $x$.
\end{document}
```"""
        self.assertEqual(sanitize_latex(raw), "Hello $x$.")

    def test_merges_chapter_label_with_following_title_section(self) -> None:
        raw = r"""\chapter*{Chapter 1}
\section*{Conditional expectations}
\section*{1.1 The Hilbert space \(L^2\)}
"""
        result = sanitize_latex(raw)
        self.assertIn(r"\chapter{Conditional expectations}", result)
        self.assertIn(r"\section{The Hilbert space \(L^2\)}", result)

    def test_removes_printed_numbers_from_environments(self) -> None:
        raw = r"""\begin{Theorem}[1.1]
X
\end{Theorem}
\begin{definition}{1.2}
Y
\end{definition}
"""
        result = sanitize_latex(raw)
        self.assertIn(r"\begin{theorem}", result)
        self.assertIn(r"\begin{definition}", result)
        self.assertNotIn("[1.1]", result)
        self.assertNotIn("{1.2}", result)

    def test_removes_standalone_page_number(self) -> None:
        raw = "Text\n\n\\begin{center}3\\end{center}\n"
        self.assertEqual(sanitize_latex(raw, page_number=3).strip(), "Text")

    def test_extracts_uncertain_markers(self) -> None:
        raw = r"Let \ocruncertain{x} be given. % OCR-UNCERTAIN: subscript"
        self.assertEqual(
            extract_uncertain(raw),
            ["x", "subscript"],
        )

    def test_plain_text_and_words(self) -> None:
        raw = r"\section{Hello world} Let \(x^2\) be \textbf{positive}."
        plain = latex_to_plain_text(raw)
        self.assertIn("positive", plain)
        self.assertIn("hello", content_words(plain))


if __name__ == "__main__":
    unittest.main()
