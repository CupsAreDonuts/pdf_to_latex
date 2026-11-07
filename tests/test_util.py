from __future__ import annotations

import unittest

from pdf_to_latex.util import parse_page_spec, subtract_pages


class PageSpecTests(unittest.TestCase):
    def test_ranges_and_deduplication(self) -> None:
        self.assertEqual(parse_page_spec("1-3,2,7", 10), [1, 2, 3, 7])

    def test_reversed_range_is_normalised(self) -> None:
        self.assertEqual(parse_page_spec("5-3", 10), [3, 4, 5])

    def test_invalid_page_is_rejected(self) -> None:
        with self.assertRaises(Exception):
            parse_page_spec("1,99", 10)

    def test_skip_pages(self) -> None:
        self.assertEqual(subtract_pages([1, 2, 3, 4], "2-3", 10), [1, 4])


if __name__ == "__main__":
    unittest.main()
