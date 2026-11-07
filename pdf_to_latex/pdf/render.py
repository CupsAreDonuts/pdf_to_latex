"""Render PDF pages to images suitable for a vision model."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageStat

from ..exceptions import PdfError
from ..util import ensure_dir, run_command, which_or_fail


def render_page_image(
    pdf: Path,
    page: int,
    out_dir: Path,
    *,
    dpi: int = 200,
    max_width: int = 1600,
    jpeg_quality: int = 88,
) -> Path:
    """Render one page to a compact JPEG and return its path."""
    which_or_fail("pdftoppm")
    ensure_dir(out_dir)
    stem = out_dir / f"page-{page:04d}"
    png_path = stem.with_suffix(".png")
    jpg_path = stem.with_suffix(".jpg")

    proc = run_command(
        [
            "pdftoppm",
            "-f",
            str(page),
            "-l",
            str(page),
            "-r",
            str(dpi),
            "-png",
            "-singlefile",
            str(pdf),
            str(stem),
        ],
        timeout=120,
    )
    if proc.returncode != 0 or not png_path.exists():
        raise PdfError(
            f"Could not render page {page}:\n"
            f"{proc.stderr.strip() or proc.stdout.strip() or 'pdftoppm produced no output'}"
        )

    preprocess_image(png_path, jpg_path, max_width=max_width, quality=jpeg_quality)
    return jpg_path


def preprocess_image(
    source: Path,
    destination: Path,
    *,
    max_width: int = 1600,
    quality: int = 88,
) -> Path:
    """Downscale and convert a page image to JPEG.

    Keeping the image near 1600 px wide is a compromise between readability of
    subscripts and API request size.  The model can still read 200 dpi output.
    """
    ensure_dir(destination.parent)
    with Image.open(source) as image:
        image = image.convert("RGB")
        width, height = image.size
        if width > max_width:
            new_height = max(1, round(height * max_width / width))
            image = image.resize((max_width, new_height), Image.Resampling.LANCZOS)
        image.save(destination, format="JPEG", quality=quality, optimize=True)
    return destination


def image_ink_ratio(path: Path, *, sample_width: int = 900) -> float:
    """Fraction of dark pixels, used only to recognise blank scanned pages."""
    with Image.open(path) as image:
        gray = image.convert("L")
        width, height = gray.size
        if width > sample_width:
            new_height = max(1, round(height * sample_width / width))
            gray = gray.resize((sample_width, new_height), Image.Resampling.BOX)
        histogram = gray.histogram()
    dark = sum(histogram[:200])
    total = max(sum(histogram), 1)
    return dark / total


def is_blank_image(path: Path, *, threshold: float = 0.003) -> bool:
    return image_ink_ratio(path) < threshold


def image_statistics(path: Path) -> dict[str, float | int]:
    """Small diagnostics block for the report."""
    with Image.open(path) as image:
        width, height = image.size
        stat = ImageStat.Stat(image.convert("L"))
    return {
        "width": width,
        "height": height,
        "mean_intensity": round(float(stat.mean[0]), 2),
        "ink_ratio": round(image_ink_ratio(path), 6),
    }
