"""Extract the PDF text layer and classify obvious non-content pages."""

from __future__ import annotations

import re
from pathlib import Path

from ..util import run_command, which_or_fail


def extract_page_text(pdf: Path, page: int) -> str:
    """Return the text layer of one page, or an empty string if there is none."""
    which_or_fail("pdftotext")
    proc = run_command(
        [
            "pdftotext",
            "-f",
            str(page),
            "-l",
            str(page),
            "-layout",
            str(pdf),
            "-",
        ],
        timeout=60,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.replace("\f", "").strip()


def extract_all_text(pdf: Path) -> str:
    """Return the whole PDF text layer. Useful for reports and validation."""
    which_or_fail("pdftotext")
    proc = run_command(["pdftotext", "-layout", str(pdf), "-"], timeout=180)
    if proc.returncode != 0:
        return ""
    return proc.stdout.replace("\f", "")


_PAGE_NUMBER_LINE_RE = re.compile(r"^\s*\d{1,4}\s*$")
_TOC_HEADING_RE = re.compile(
    r"(?:table\s+of\s+contents|contents|inhalts?(?:verzeichnis)?|sommaire|indice)\s*:?",
    re.IGNORECASE,
)


def is_blank_text(text: str) -> bool:
    """True when the text layer carries no meaningful content.

    Scanned pages have no text layer at all; digital pages may carry only a
    printed page number.  Any other alphanumeric line counts as content, no
    matter how short, so sparse title or formula pages are not dropped.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or _PAGE_NUMBER_LINE_RE.fullmatch(stripped):
            continue
        if any(character.isalnum() for character in stripped):
            return False
    return True


def looks_like_toc(text: str, previous_page_was_toc: bool = False) -> bool:
    """Heuristic for a printed table of contents.

    The reconstructed document should use ``\\tableofcontents`` instead of
    transcribing the stale printed page numbers.  The heuristic deliberately
    requires either an explicit heading near the top of the page or a
    contiguous TOC run.
    """
    if not text.strip():
        return False

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    explicit_heading = any(
        _TOC_HEADING_RE.fullmatch(line) for line in lines[:5]
    )
    dot_leader_lines = sum(
        1
        for line in lines
        if re.search(r"(?:\.\s*){2,}\d+\s*$", line)
        or re.search(r"\S\s{2,}\d+\s*$", line)
    )
    digit_ratio = sum(ch.isdigit() for ch in text) / max(len(text), 1)

    if explicit_heading and (dot_leader_lines >= 3 or digit_ratio > 0.04):
        return True
    if previous_page_was_toc and dot_leader_lines >= 2:
        return True
    return False
