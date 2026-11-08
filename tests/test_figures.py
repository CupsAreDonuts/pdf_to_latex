from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from pdf_to_latex.exceptions import PdfError
from pdf_to_latex.models import PageSlice
from pdf_to_latex.pdf.figures import (
    FigureBox,
    FigureExtractor,
    crop_box,
    discard_figure_placeholders,
    map_slice_box,
    pad_box,
    parse_figure_boxes,
    replace_placeholders,
    strip_figure_markers,
)

FIGURE_ENVIRONMENT = (
    "% FIG-BOX 1: 100,150,500,450\n"
    "\\begin{figure}[htbp]\n"
    "\\centering\n"
    "\\includegraphics[width=0.8\\linewidth]{FIG:1}\n"
    "\\caption{A plot.}\n"
    "\\end{figure}"
)


def _page_image(root: Path, *, width: int = 1000, height: int = 1400) -> Path:
    image = Image.new("RGB", (width, height), "white")
    ImageDraw.Draw(image).rectangle((100, 200, 500, 600), fill="black")
    path = root / "page.png"
    image.save(path)
    return path


class StubFigureExtractor(FigureExtractor):
    """FigureExtractor with the PDF render replaced by a synthetic page."""

    def __init__(self, page_png: Path, **kwargs) -> None:
        kwargs.setdefault("pdf", Path("unused.pdf"))
        super().__init__(**kwargs)
        self._stub_page_png = page_png

    def _page_png(self, page: int) -> Path:
        return self._stub_page_png


class FailingFigureExtractor(StubFigureExtractor):
    def _page_png(self, page: int) -> Path:
        raise PdfError("pdftoppm unavailable")


class FigureBoxParsingTests(unittest.TestCase):
    def test_parses_per_mille_coordinates(self) -> None:
        boxes, warnings = parse_figure_boxes(
            "% FIG-BOX 1: 100,200,800,900\n"
        )
        self.assertEqual(warnings, [])
        self.assertAlmostEqual(boxes[1].x0, 0.1)
        self.assertAlmostEqual(boxes[1].y1, 0.9)

    def test_parses_fractional_coordinates(self) -> None:
        boxes, _ = parse_figure_boxes("% FIG-BOX 2: 0.1,0.2,0.8,0.9")
        self.assertAlmostEqual(boxes[2].x1, 0.8)

    def test_rejects_inverted_box_with_a_warning(self) -> None:
        boxes, warnings = parse_figure_boxes("% FIG-BOX 3: 800,200,100,900")
        self.assertNotIn(3, boxes)
        self.assertTrue(any("invalid" in warning for warning in warnings))

    def test_rejects_box_outside_the_page(self) -> None:
        boxes, warnings = parse_figure_boxes("% FIG-BOX 4: 0,0,1200,900")
        self.assertNotIn(4, boxes)
        self.assertTrue(any("FIG-BOX 4" in warning for warning in warnings))

    def test_last_duplicate_wins(self) -> None:
        boxes, warnings = parse_figure_boxes(
            "% FIG-BOX 5: 0,0,500,500\n% FIG-BOX 5: 100,100,600,600\n"
        )
        self.assertAlmostEqual(boxes[5].x0, 0.1)
        self.assertTrue(any("more than once" in warning for warning in warnings))

    def test_invalid_duplicate_keeps_the_earlier_valid_box(self) -> None:
        boxes, warnings = parse_figure_boxes(
            "% FIG-BOX 6: 0,0,500,500\n% FIG-BOX 6: 900,900,100,100\n"
        )
        self.assertIn(6, boxes)
        self.assertTrue(any("FIG-BOX 6" in warning for warning in warnings))


class BoxGeometryTests(unittest.TestCase):
    def test_slice_coordinates_are_mapped_to_the_page(self) -> None:
        box = FigureBox(0.1, 0.0, 0.5, 1.0)
        slice_ = PageSlice(
            page=3, index=2, count=2, y0=700, y1=1400, image_path=Path("x.jpg")
        )
        mapped = map_slice_box(box, slice_, page_height=1400)
        self.assertAlmostEqual(mapped.y0, 0.5)
        self.assertAlmostEqual(mapped.y1, 1.0)
        self.assertAlmostEqual(mapped.x0, 0.1)

    def test_padding_is_clamped_to_the_page(self) -> None:
        padded = pad_box(FigureBox(0.0, 0.0, 1.0, 1.0), 0.1)
        self.assertEqual(padded.as_tuple(), (0.0, 0.0, 1.0, 1.0))

    def test_padding_grows_the_box(self) -> None:
        padded = pad_box(FigureBox(0.4, 0.4, 0.6, 0.6), 0.5)
        self.assertAlmostEqual(padded.x0, 0.3)
        self.assertAlmostEqual(padded.x1, 0.7)


class CropTests(unittest.TestCase):
    def test_crop_saves_a_non_blank_region(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            page = _page_image(root)
            destination = root / "out" / "figure.png"
            self.assertTrue(
                crop_box(page, FigureBox(0.1, 0.15, 0.5, 0.45), destination)
            )
            self.assertTrue(destination.exists())
            with Image.open(destination) as crop:
                self.assertGreater(crop.size[0], 0)

    def test_blank_region_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            page = _page_image(root)
            self.assertFalse(
                crop_box(page, FigureBox(0.7, 0.1, 0.9, 0.3), root / "blank.png")
            )

    def test_tiny_region_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            page = _page_image(root)
            self.assertFalse(
                crop_box(page, FigureBox(0.5, 0.5, 0.501, 0.501), root / "tiny.png")
            )

    def test_uniform_dark_region_is_kept(self) -> None:
        # A solid black figure area is content, not a blank page region.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            page = _page_image(root)
            self.assertTrue(
                crop_box(page, FigureBox(0.2, 0.2, 0.4, 0.35), root / "dark.png")
            )


class PlaceholderTests(unittest.TestCase):
    def test_replaces_placeholder_and_keeps_options(self) -> None:
        latex = "\\includegraphics[width=3cm]{FIG:2}"
        result = replace_placeholders(latex, {2: "figures/doc/x.png"})
        self.assertEqual(
            result, "\\includegraphics[width=3cm]{figures/doc/x.png}"
        )

    def test_starred_includegraphics_is_replaced(self) -> None:
        result = replace_placeholders(
            "\\includegraphics*[width=3cm]{FIG:2}", {2: "figures/doc/x.png"}
        )
        self.assertEqual(
            result, "\\includegraphics*[width=3cm]{figures/doc/x.png}"
        )

    def test_missing_target_becomes_a_placeholder_macro(self) -> None:
        result = replace_placeholders("\\includegraphics{FIG:7}", {7: None})
        self.assertEqual(result, "\\figureplaceholder{7}")

    def test_disabling_figures_discards_placeholders(self) -> None:
        extraction = discard_figure_placeholders(FIGURE_ENVIRONMENT)
        self.assertIn("\\figureplaceholder{1}", extraction.latex)
        self.assertNotIn("FIG-BOX", extraction.latex)
        self.assertNotIn("FIG:1", extraction.latex)
        self.assertEqual(extraction.figures, [])

    def test_unrelated_includegraphics_is_untouched(self) -> None:
        latex = "\\includegraphics{other.png}"
        self.assertEqual(replace_placeholders(latex, {}), latex)

    def test_markers_are_stripped(self) -> None:
        self.assertEqual(strip_figure_markers(FIGURE_ENVIRONMENT).count("FIG-BOX"), 0)


class ResolveTests(unittest.TestCase):
    def _extractor(self, root: Path, page: Path) -> StubFigureExtractor:
        return StubFigureExtractor(
            page,
            figures_dir=root / "figures" / "doc",
            relative_dir="figures/doc",
            render_dir=root / "render",
            dpi=300,
            padding=0.02,
        )

    def test_resolves_a_crop_and_records_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            page = _page_image(root)
            extraction = self._extractor(root, page).resolve(
                page=1, latex=FIGURE_ENVIRONMENT
            )
            self.assertNotIn("FIG:", extraction.latex)
            self.assertNotIn("FIG-BOX", extraction.latex)
            self.assertEqual(len(extraction.figures), 1)
            record = extraction.figures[0]
            self.assertEqual(record.source, "crop")
            self.assertEqual(record.path, "figures/doc/p0001-f01.png")
            self.assertEqual(extraction.warnings, [])
            self.assertTrue((root / record.path).exists())

    def test_missing_box_uses_the_whole_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            page = _page_image(root)
            extraction = self._extractor(root, page).resolve(
                page=1, latex="\\includegraphics{FIG:1}"
            )
            record = extraction.figures[0]
            self.assertEqual(record.source, "page")
            self.assertEqual(record.path, "figures/doc/p0001-page.png")
            self.assertTrue(extraction.warnings)

    def test_slice_boxes_are_mapped_before_cropping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            page = _page_image(root)
            slice_ = PageSlice(
                page=1,
                index=1,
                count=2,
                y0=0,
                y1=700,
                image_path=Path("slice.jpg"),
            )
            extraction = self._extractor(root, page).resolve(
                page=1,
                latex="% FIG-BOX 1: 100,0,500,1000\n\\includegraphics{FIG:1}",
                slice_=slice_,
                ocr_page_image=page,
            )
            self.assertEqual(extraction.figures[0].source, "crop")
            self.assertEqual(
                extraction.figures[0].path, "figures/doc/p0001-s01-f01.png"
            )

    def test_render_failure_leaves_a_placeholder_macro(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            page = _page_image(root)
            extractor = FailingFigureExtractor(
                page,
                figures_dir=root / "figures" / "doc",
                relative_dir="figures/doc",
                render_dir=root / "render",
            )
            extraction = extractor.resolve(page=1, latex="\\includegraphics{FIG:1}")
            self.assertIn("\\figureplaceholder{1}", extraction.latex)
            self.assertEqual(extraction.figures[0].source, "missing")

    def test_whole_page_fragment_uses_a_page_sized_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            page = _page_image(root)
            extraction = self._extractor(root, page).whole_page_fragment(
                1, reason="OCR produced no LaTeX fragment"
            )
            self.assertIn("figures/doc/p0001-page.png", extraction.latex)
            self.assertIn("width=\\linewidth", extraction.latex)
            self.assertIn("\\clearpage", extraction.latex)
            self.assertEqual(extraction.figures[0].source, "page")

    def test_variants_do_not_overwrite_an_adopted_crop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            page = _page_image(root)
            extractor = self._extractor(root, page)
            first = extractor.resolve(page=1, latex=FIGURE_ENVIRONMENT)
            second = extractor.resolve(
                page=1, latex=FIGURE_ENVIRONMENT, variant="repair"
            )
            self.assertNotEqual(
                first.figures[0].path, second.figures[0].path
            )
            self.assertTrue((root / first.figures[0].path).exists())
            self.assertTrue((root / second.figures[0].path).exists())


if __name__ == "__main__":
    unittest.main()
