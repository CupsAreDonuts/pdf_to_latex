"""Turn model-reported figure boxes into cropped artwork for the LaTeX output.

The vision model does not redraw figures.  Instead it emits a ``% FIG-BOX``
comment with a rectangle and an ``\\includegraphics{FIG:<n>}`` placeholder.
This module resolves those placeholders against a high-resolution render of
the original PDF page, falling back to the whole page when a crop is not
usable.
"""

from __future__ import annotations

import re
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from ..exceptions import PipelineError
from ..models import FigureRecord, PageSlice
from ..util import ensure_dir
from .render import render_page_png

_NUMBER = r"-?\d+(?:\.\d+)?"
_FIGURE_BOX_RE = re.compile(
    rf"(?m)^[ \t]*%[ \t]*FIG-BOX[ \t]+(?P<id>\d+)[ \t]*:[ \t]*"
    rf"(?P<x0>{_NUMBER})[ \t]*,[ \t]*(?P<y0>{_NUMBER})[ \t]*,"
    rf"[ \t]*(?P<x1>{_NUMBER})[ \t]*,[ \t]*(?P<y1>{_NUMBER})"
)
_FIGURE_PLACEHOLDER_RE = re.compile(
    r"\\includegraphics(?P<star>\*)?(?P<options>\s*\[[^\]]*\])?\s*"
    r"\{\s*FIG\s*:\s*(?P<id>\d+)\s*\}"
)

# A crop smaller than this is almost certainly a bad box, not a real figure.
_MIN_CROP_PIXELS = 16
# A uniform crop at least this bright is treated as an empty page area.
_BLANK_GRAY_LEVEL = 245


@dataclass(frozen=True)
class FigureBox:
    """A rectangle in page-normalised coordinates with a top-left origin."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def is_valid(self) -> bool:
        return (
            0.0 <= self.x0 < self.x1 <= 1.0
            and 0.0 <= self.y0 < self.y1 <= 1.0
        )

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)


@dataclass
class FigureExtraction:
    """Result of resolving every figure placeholder in one fragment."""

    latex: str
    figures: list[FigureRecord]
    warnings: list[str]


def parse_figure_boxes(latex: str) -> tuple[dict[int, FigureBox], list[str]]:
    """Parse ``% FIG-BOX <n>: x0,y0,x1,y1`` markers from model output.

    Coordinates may be integers on a 0-1000 scale (the prompt convention) or
    fractions in 0-1.  Invalid boxes are dropped and reported as warnings so
    the caller can fall back to the whole page.
    """
    boxes: dict[int, FigureBox] = {}
    warnings: list[str] = []
    for match in _FIGURE_BOX_RE.finditer(latex):
        identifier = int(match.group("id"))
        values = tuple(
            float(match.group(name)) for name in ("x0", "y0", "x1", "y1")
        )
        box = _box_from_values(values)
        if box is None:
            warnings.append(
                f"FIG-BOX {identifier} is invalid or outside the page; it was ignored."
            )
            continue
        if identifier in boxes:
            warnings.append(
                f"FIG-BOX {identifier} appears more than once; using the last box."
            )
        boxes[identifier] = box
    return boxes, warnings


def _box_from_values(values: tuple[float, ...]) -> FigureBox | None:
    largest = max(values)
    if largest > 1000.0:
        return None
    scale = 1000.0 if largest > 1.0 else 1.0
    box = FigureBox(*(value / scale for value in values))
    return box if box.is_valid else None


def map_slice_box(box: FigureBox, slice_: PageSlice, page_height: int) -> FigureBox:
    """Translate slice-relative coordinates into page-relative coordinates.

    Slices span the full page width, so only the vertical fraction changes.
    ``slice_.y0``/``slice_.y1`` are pixel offsets in the OCR page image.
    """
    if page_height <= 0:
        raise ValueError("page_height must be positive")
    span = slice_.y1 - slice_.y0
    return FigureBox(
        box.x0,
        (slice_.y0 + box.y0 * span) / page_height,
        box.x1,
        (slice_.y0 + box.y1 * span) / page_height,
    )


def pad_box(box: FigureBox, padding: float) -> FigureBox:
    """Grow *box* by a fraction of its own size, clamped to the page."""
    padding = max(0.0, padding)
    dx = (box.x1 - box.x0) * padding
    dy = (box.y1 - box.y0) * padding
    return FigureBox(
        max(0.0, box.x0 - dx),
        max(0.0, box.y0 - dy),
        min(1.0, box.x1 + dx),
        min(1.0, box.y1 + dy),
    )


def crop_box(page_image: Path, box: FigureBox, destination: Path) -> bool:
    """Crop *box* out of *page_image* and save it as PNG.

    Returns ``False`` when the crop is degenerate or visually blank, in which
    case the caller should fall back to the whole page.
    """
    with Image.open(page_image) as image:
        width, height = image.size
        left = int(round(box.x0 * width))
        upper = int(round(box.y0 * height))
        right = int(round(box.x1 * width))
        lower = int(round(box.y1 * height))
        if right - left < _MIN_CROP_PIXELS or lower - upper < _MIN_CROP_PIXELS:
            return False
        crop = image.crop((left, upper, right, lower)).convert("RGB")

    low, high = crop.convert("L").getextrema()
    if high - low < 8 and low >= _BLANK_GRAY_LEVEL:
        return False

    ensure_dir(destination.parent)
    crop.save(destination, format="PNG", optimize=True)
    return True


def strip_figure_markers(latex: str) -> str:
    """Remove ``% FIG-BOX`` provenance comments from the delivered fragment."""
    return re.sub(r"(?m)^[ \t]*%[ \t]*FIG-BOX[^\n]*\n?", "", latex)


def replace_placeholders(
    latex: str, targets: dict[int, str | None]
) -> str:
    """Replace ``\\includegraphics{FIG:<n>}`` with resolved image paths.

    A target of ``None`` means no image could be produced; the placeholder is
    replaced by the ``\\figureplaceholder`` macro so the fragment still
    compiles.
    """

    def substitute(match: re.Match[str]) -> str:
        identifier = int(match.group("id"))
        if identifier not in targets:
            return match.group(0)
        target = targets[identifier]
        if target is None:
            return f"\\figureplaceholder{{{identifier}}}"
        star = match.group("star") or ""
        options = match.group("options") or ""
        return f"\\includegraphics{star}{options}{{{target}}}"

    return _FIGURE_PLACEHOLDER_RE.sub(substitute, latex)


def discard_figure_placeholders(latex: str) -> FigureExtraction:
    """Replace placeholders with visible markers when extraction is disabled."""
    matches = list(_FIGURE_PLACEHOLDER_RE.finditer(latex))
    targets = {int(match.group("id")): None for match in matches}
    return FigureExtraction(
        strip_figure_markers(replace_placeholders(latex, targets)), [], []
    )


def _image_height(path: Path | None) -> int | None:
    if path is None:
        return None
    try:
        with Image.open(path) as image:
            return image.size[1]
    except OSError:
        return None


class FigureExtractor:
    """Resolve figure placeholders against high-resolution page renders."""

    def __init__(
        self,
        *,
        pdf: Path,
        figures_dir: Path,
        relative_dir: str,
        render_dir: Path,
        dpi: int = 300,
        padding: float = 0.02,
    ) -> None:
        self.pdf = pdf
        self.figures_dir = figures_dir
        self.relative_dir = relative_dir.rstrip("/")
        self.render_dir = render_dir
        self.dpi = dpi
        self.padding = padding
        self._page_images: dict[int, Path] = {}
        self._whole_pages_written: set[int] = set()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def resolve(
        self,
        *,
        page: int,
        latex: str,
        slice_: PageSlice | None = None,
        ocr_page_image: Path | None = None,
        variant: str = "",
    ) -> FigureExtraction:
        """Resolve every placeholder in one full-page or slice fragment.

        ``variant`` distinguishes repeated resolutions of the same page (for
        example a repair attempt) so a rejected candidate cannot overwrite the
        crops referenced by an already adopted fragment.
        """
        boxes, warnings = parse_figure_boxes(latex)
        matches = list(_FIGURE_PLACEHOLDER_RE.finditer(latex))
        if not matches:
            if boxes:
                warnings.append(
                    f"{len(boxes)} FIG-BOX marker(s) had no matching "
                    "\\includegraphics{FIG:<n>} placeholder and were ignored."
                )
            return FigureExtraction(strip_figure_markers(latex), [], warnings)

        identifiers = _unique_identifiers(matches)
        try:
            page_png = self._page_png(page)
        except (PipelineError, OSError) as exc:
            warnings.append(
                f"Could not render page {page} at {self.dpi} dpi for figures: {exc}"
            )
            records = [
                FigureRecord(
                    page=page,
                    identifier=identifier,
                    path="",
                    source="missing",
                    reason="high-resolution page render failed",
                )
                for identifier in identifiers
            ]
            unresolved: dict[int, str | None] = {
                identifier: None for identifier in identifiers
            }
            return FigureExtraction(
                strip_figure_markers(replace_placeholders(latex, unresolved)),
                records,
                warnings,
            )

        page_height = _image_height(ocr_page_image)
        targets: dict[int, str | None] = {}
        records: list[FigureRecord] = []
        for identifier in identifiers:
            try:
                target, record, warning = self._resolve_one(
                    page=page,
                    identifier=identifier,
                    box=boxes.get(identifier),
                    slice_=slice_,
                    page_height=page_height,
                    page_png=page_png,
                    variant=variant,
                )
            except OSError as exc:
                target = None
                record = FigureRecord(
                    page=page,
                    identifier=identifier,
                    path="",
                    source="missing",
                    reason=f"could not write the figure image: {exc}",
                )
                warning = (
                    f"Figure {identifier} on page {page} could not be written: {exc}"
                )
            targets[identifier] = target
            records.append(record)
            if warning:
                warnings.append(warning)

        warnings.extend(
            f"FIG-BOX {identifier} has no matching "
            f"\\includegraphics{{FIG:{identifier}}} placeholder; the box was ignored."
            for identifier in sorted(boxes)
            if identifier not in identifiers
        )
        resolved = strip_figure_markers(replace_placeholders(latex, targets))
        return FigureExtraction(resolved, records, warnings)

    def whole_page_fragment(self, page: int, *, reason: str) -> FigureExtraction:
        """Build a figure-only fragment from the whole page image.

        Used when OCR produced no usable LaTeX at all, so the page would
        otherwise be missing from the output document.
        """
        try:
            page_png = self._page_png(page)
            destination = self._whole_page_file(page, page_png)
        except (PipelineError, OSError) as exc:
            return FigureExtraction(
                "",
                [],
                [f"Could not render a whole-page fallback for page {page}: {exc}"],
            )
        relative = self._relative(destination)
        latex = (
            "\\clearpage\n"
            "\\begin{center}\n"
            "\\includegraphics[width=\\linewidth,height=0.9\\textheight,"
            f"keepaspectratio]{{{relative}}}\n"
            "\\end{center}\n"
            "\\clearpage"
        )
        record = FigureRecord(
            page=page,
            identifier=0,
            path=relative,
            source="page",
            reason=reason,
        )
        return FigureExtraction(latex, [record], [])

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _resolve_one(
        self,
        *,
        page: int,
        identifier: int,
        box: FigureBox | None,
        slice_: PageSlice | None,
        page_height: int | None,
        page_png: Path,
        variant: str,
    ) -> tuple[str | None, FigureRecord, str]:
        reason = ""
        if box is not None and slice_ is not None:
            if page_height is None:
                box = None
                reason = "the slice position could not be mapped to the page"
            else:
                mapped = map_slice_box(box, slice_, page_height)
                box = mapped if mapped.is_valid else None
                if box is None:
                    reason = "the reported box lies outside the page"

        if box is not None:
            destination = self.figures_dir / self._crop_filename(
                page, identifier, slice_, variant
            )
            if crop_box(page_png, pad_box(box, self.padding), destination):
                path = self._relative(destination)
                return (
                    path,
                    FigureRecord(
                        page=page,
                        identifier=identifier,
                        path=path,
                        source="crop",
                        box=box.as_tuple(),
                    ),
                    "",
                )
            reason = "the reported box produced an empty crop"

        if not reason:
            reason = "no usable FIG-BOX marker was reported"

        destination = self._whole_page_file(page, page_png)
        path = self._relative(destination)
        record = FigureRecord(
            page=page,
            identifier=identifier,
            path=path,
            source="page",
            box=box.as_tuple() if box is not None else None,
            reason=reason,
        )
        warning = (
            f"Figure {identifier} on page {page}: {reason}; "
            "the whole page was used instead."
        )
        return path, record, warning

    def _page_png(self, page: int) -> Path:
        with self._lock:
            cached = self._page_images.get(page)
            if cached is not None and cached.exists():
                return cached
        # Render outside the lock: different pages may be rendered in parallel
        # by the OCR worker pool. The same page is never processed twice at
        # once because it maps to a single PagePlan.
        path = render_page_png(self.pdf, page, self.render_dir, dpi=self.dpi)
        with self._lock:
            self._page_images[page] = path
        return path

    def _whole_page_file(self, page: int, page_png: Path) -> Path:
        destination = self.figures_dir / f"p{page:04d}-page.png"
        with self._lock:
            if page not in self._whole_pages_written:
                ensure_dir(destination.parent)
                shutil.copyfile(page_png, destination)
                self._whole_pages_written.add(page)
        return destination

    def _relative(self, path: Path) -> str:
        return f"{self.relative_dir}/{path.name}"

    @staticmethod
    def _crop_filename(
        page: int, identifier: int, slice_: PageSlice | None, variant: str
    ) -> str:
        prefix = f"p{page:04d}"
        if slice_ is not None:
            prefix += f"-s{slice_.index:02d}"
        if variant:
            prefix += f"-{variant}"
        return f"{prefix}-f{identifier:02d}.png"


def _unique_identifiers(matches: list[re.Match[str]]) -> list[int]:
    seen: set[int] = set()
    identifiers: list[int] = []
    for match in matches:
        identifier = int(match.group("id"))
        if identifier not in seen:
            seen.add(identifier)
            identifiers.append(identifier)
    return identifiers
