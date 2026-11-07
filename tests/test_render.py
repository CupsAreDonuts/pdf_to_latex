from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from pdf_to_latex.pdf.render import (
    image_dark_pixels,
    image_ink_ratio,
    is_blank_image,
)


class BlankImageTests(unittest.TestCase):
    def _image(self, root: Path, name: str, draw=None) -> Path:
        image = Image.new("RGB", (900, 1200), "white")
        if draw is not None:
            draw(ImageDraw.Draw(image))
        path = root / name
        image.save(path, format="JPEG", quality=88, optimize=True)
        return path

    def test_white_page_is_blank(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._image(Path(tmp), "blank.jpg")
            self.assertTrue(is_blank_image(path))

    def test_tiny_speck_is_blank(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._image(
                Path(tmp), "speck.jpg", lambda draw: draw.rectangle((10, 10, 12, 12), fill="black")
            )
            self.assertTrue(is_blank_image(path))

    def test_single_short_line_is_not_blank(self) -> None:
        # Regression: ~0.17% ink is below the old ratio-only threshold, but a
        # real word is still visible and must reach OCR.
        with tempfile.TemporaryDirectory() as tmp:
            path = self._image(
                Path(tmp),
                "sparse.jpg",
                lambda draw: draw.rectangle((40, 100, 160, 115), fill="black"),
            )
            self.assertLess(image_ink_ratio(path), 0.003)
            self.assertGreaterEqual(image_dark_pixels(path), 100)
            self.assertFalse(is_blank_image(path))


if __name__ == "__main__":
    unittest.main()
