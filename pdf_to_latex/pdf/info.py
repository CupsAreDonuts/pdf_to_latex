"""Read basic PDF metadata with ``pdfinfo``."""

from __future__ import annotations

import re
from pathlib import Path

from ..exceptions import PdfError
from ..models import PdfInfo
from ..util import run_command, which_or_fail


def inspect_pdf(path: Path) -> PdfInfo:
    """Return page count, title and page size for *path*."""
    which_or_fail("pdfinfo")
    if not path.exists():
        raise PdfError(f"PDF does not exist: {path}")
    if path.stat().st_size == 0:
        raise PdfError(f"PDF is empty: {path}")

    proc = run_command(["pdfinfo", str(path)], timeout=60)
    if proc.returncode != 0:
        raise PdfError(
            f"pdfinfo failed for {path}:\n{proc.stderr.strip() or proc.stdout.strip()}"
        )

    raw: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        raw[key.strip()] = value.strip()

    try:
        pages = int(raw.get("Pages", "0"))
    except ValueError as exc:
        raise PdfError(f"Could not read the page count from pdfinfo: {raw.get('Pages')!r}") from exc
    if pages < 1:
        raise PdfError("The PDF reports no pages.")

    width = height = None
    size_match = re.search(
        r"([0-9.]+)\s*x\s*([0-9.]+)\s*pts", raw.get("Page size", "")
    )
    if size_match:
        width = float(size_match.group(1))
        height = float(size_match.group(2))

    return PdfInfo(
        path=path,
        pages=pages,
        title=raw.get("Title") or None,
        page_width_pt=width,
        page_height_pt=height,
        raw=raw,
    )


def pdf_page_count(path: Path) -> int | None:
    """Best-effort page count for a compiled PDF."""
    if not path.exists():
        return None
    proc = run_command(["pdfinfo", str(path)], timeout=30)
    if proc.returncode != 0:
        return None
    match = re.search(r"(?m)^Pages:\s*(\d+)\s*$", proc.stdout)
    return int(match.group(1)) if match else None
