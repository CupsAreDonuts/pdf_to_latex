from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from pdf_to_latex.pdf.slices import make_slices


class SliceTests(unittest.TestCase):
    def test_splits_on_blank_rows_and_keeps_both_halves(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = Image.new("RGB", (600, 1200), "white")
            draw = ImageDraw.Draw(image)
            # Two dark text bands with a wide blank gap in the middle.
            draw.rectangle((50, 100, 550, 430), fill="black")
            draw.rectangle((50, 770, 550, 1100), fill="black")
            source = root / "page.png"
            image.save(source)

            slices = make_slices(source, root / "out", 1, count=2)
            self.assertEqual(len(slices), 2)
            self.assertEqual(slices[0].y0, 0)
            self.assertEqual(slices[1].y1, 1200)
            self.assertLessEqual(slices[0].y1, slices[1].y0)
            # The cut should be in the blank gap, not through a dark band.
            self.assertGreaterEqual(slices[0].y1, 430)
            self.assertLessEqual(slices[0].y1, 770)
            for item in slices:
                self.assertTrue(item.image_path.exists())

    def test_falls_back_to_half_when_no_whitespace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = Image.new("RGB", (300, 600), "black")
            source = root / "page.png"
            image.save(source)
            slices = make_slices(source, root / "out", 2, count=2)
            self.assertEqual(len(slices), 2)
            self.assertEqual(slices[1].y1, 600)


if __name__ == "__main__":
    unittest.main()
