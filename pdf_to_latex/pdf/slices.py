"""Split a tall page image at whitespace rows when full-page OCR is insufficient."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from ..models import PageSlice
from ..util import ensure_dir


def _row_intensities(gray: Image.Image) -> list[int]:
    """Return one mean intensity value per image row."""
    width, height = gray.size
    if height == 0:
        return []
    # BOX resampling to width=1 computes the row mean efficiently.
    strip = gray.resize((1, height), Image.Resampling.BOX)
    if hasattr(strip, "get_flattened_data"):
        data = strip.get_flattened_data()
    else:  # Pillow < 12
        data = strip.getdata()
    return [int(value) for value in data]


def _find_cut_rows(row_means: list[int], count: int) -> list[int]:
    """Choose near-white rows near the requested fractional boundaries."""
    height = len(row_means)
    if count <= 1 or height < 80:
        return []

    targets = [round(height * index / count) for index in range(1, count)]
    window = max(24, int(height * 0.12))
    min_gap = max(40, height // (count * 5))
    cuts: list[int] = []

    for target in targets:
        low = max(1, target - window)
        high = min(height - 2, target + window)
        blank_rows = [
            row for row in range(low, high + 1) if row_means[row] >= 247
        ]

        if blank_rows:
            # Pick the blank row closest to the target.  A run of blank rows is
            # safe to cut anywhere; the closest row keeps slices balanced.
            cut = min(blank_rows, key=lambda row: abs(row - target))
        else:
            # No clean whitespace: use the whitest row in the window.
            cut = max(range(low, high + 1), key=lambda row: row_means[row])

        if cuts and cut - cuts[-1] < min_gap:
            cut = min(height - 1, cuts[-1] + min_gap)
        if cut <= 0 or cut >= height - 1:
            continue
        cuts.append(cut)

    return sorted(set(cuts))


def make_slices(
    image_path: Path,
    out_dir: Path,
    page: int,
    *,
    count: int = 2,
    jpeg_quality: int = 90,
) -> list[PageSlice]:
    """Create two or more horizontal slices with no overlap.

    Cuts are placed on blank rows whenever possible, so no text line should be
    split.  If a page has no whitespace at the requested position, the whitest
    nearby row is used.
    """
    ensure_dir(out_dir)
    with Image.open(image_path) as source:
        image = source.convert("RGB")
        width, height = image.size
        cuts = _find_cut_rows(_row_intensities(image.convert("L")), count)
        boundaries = [0, *cuts, height]
        if len(boundaries) < 3:
            # Could not find a safe split; fall back to equal halves.
            boundaries = [0, height // 2, height]

        slices: list[PageSlice] = []
        for index, (top, bottom) in enumerate(
            zip(boundaries, boundaries[1:]), start=1
        ):
            if bottom <= top:
                continue
            crop = image.crop((0, top, width, bottom))
            slice_path = out_dir / f"page-{page:04d}-slice-{index:02d}.jpg"
            crop.save(slice_path, format="JPEG", quality=jpeg_quality, optimize=True)
            slices.append(
                PageSlice(
                    page=page,
                    index=index,
                    count=len(boundaries) - 1,
                    y0=top,
                    y1=bottom,
                    image_path=slice_path,
                )
            )

    # Correct the count after any degenerate slice was skipped.
    for item in slices:
        item.count = len(slices)
    return slices
