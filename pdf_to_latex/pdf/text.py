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


def is_blank_text(text: str) -> bool:
    stripped = re.sub(r"\s+", "", text)
    return len(stripped) < 20


def looks_like_toc(text: str, previous_page_was_toc: bool = False) -> bool:
    """Heuristic for a printed table of contents.

    The reconstructed document should use ``\\tableofcontents`` instead of
    transcribing the stale printed page numbers.  The heuristic deliberately
    requires either an explicit heading or a contiguous TOC run.
    """
    if not text.strip():
        return False

    head = text[:1800].lower()
    explicit_heading = any(
        phrase in head
        for phrase in (
            "table of contents",
            "contents",
            "inhalt",
            "inhaltverzeichnis",
            "sommaire",
            "indice",
        )
    )

    lines = [line for line in text.splitlines() if line.strip()]
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
