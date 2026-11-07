from __future__ import annotations

import unittest

from pdf_to_latex.pdf.text import is_blank_text, looks_like_toc


class BlankTextTests(unittest.TestCase):
    def test_truly_blank_and_page_number_only_are_blank(self) -> None:
        self.assertTrue(is_blank_text(""))
        self.assertTrue(is_blank_text("   \n\n"))
        self.assertTrue(is_blank_text("42\n"))
        self.assertTrue(is_blank_text("  \n42\n  "))

    def test_sparse_title_or_formula_is_not_blank(self) -> None:
        # Regression: this used to count fewer than 20 non-space characters
        # and was therefore classified as a blank page.
        self.assertFalse(is_blank_text("Test\nLet x^2+y^2=z^2."))
        self.assertFalse(is_blank_text("Introduction"))

    def test_page_number_with_other_text_is_not_blank(self) -> None:
        self.assertFalse(is_blank_text("3\nLet x be given."))


class TocTests(unittest.TestCase):
    def test_explicit_contents_heading_is_toc(self) -> None:
        text = (
            "Contents\n\n"
            "1 Introduction ........ 3\n"
            "2 Methods ........... 7\n"
            "3 Results ........... 11\n"
        )
        self.assertTrue(looks_like_toc(text))

    def test_prose_mentioning_contents_is_not_toc(self) -> None:
        # Regression: the old substring search matched "contents" anywhere in
        # the first 1800 characters, even in ordinary mathematical prose.
        text = (
            "The contents of this chapter are discussed in Sections 2.3 and 4.5, "
            "with 120 examples and 45 exercises."
        )
        self.assertFalse(looks_like_toc(text))

    def test_contiguous_toc_run_without_heading(self) -> None:
        text = "4 Limits ......... 20\n5 Continuity ..... 31\n"
        self.assertTrue(looks_like_toc(text, previous_page_was_toc=True))
        self.assertFalse(looks_like_toc(text, previous_page_was_toc=False))


if __name__ == "__main__":
    unittest.main()
