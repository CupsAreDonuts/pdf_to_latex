"""Compare the PDF's visible structure with the reconstructed LaTeX."""

from __future__ import annotations

import re
from collections import Counter

from ..models import PagePlan

KINDS = (
    "theorem",
    "definition",
    "lemma",
    "corollary",
    "proposition",
    "example",
    "remark",
    "exercise",
)

_PDF_HEADING_RE = re.compile(
    r"(?im)^\s*(Theorem|Definition|Lemma|Corollary|Proposition|Example|Remark|Exercise)"
    r"\s+(\d+(?:\.\d+)*)"
)
_PDF_SECTION_RE = re.compile(r"(?m)^\s*(\d+(?:\.\d+)+)\s+\S")
_TEX_HEADING_RE = re.compile(
    r"\\begin\s*\{\s*(" + "|".join(KINDS) + r")\s*\}"
)
_TEX_SECTION_RE = re.compile(r"\\(?:section|subsection|subsubsection)\*?\s*\{")


def count_pdf_headings(text: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for match in _PDF_HEADING_RE.finditer(text):
        counts[match.group(1).lower()] += 1
    return {kind: counts.get(kind, 0) for kind in KINDS}


def count_tex_headings(latex: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for match in _TEX_HEADING_RE.finditer(latex):
        counts[match.group(1).lower()] += 1
    return {kind: counts.get(kind, 0) for kind in KINDS}


def count_pdf_sections(text: str) -> int:
    return len(_PDF_SECTION_RE.findall(text))


def count_tex_sections(latex: str) -> int:
    return len(_TEX_SECTION_RE.findall(latex))


def validate_structure(
    pdf_text: str,
    tex: str,
    plans: list[PagePlan],
) -> dict[str, object]:
    pdf_counts = count_pdf_headings(pdf_text)
    tex_counts = count_tex_headings(tex)
    pdf_sections = count_pdf_sections(pdf_text)
    tex_sections = count_tex_sections(tex)

    warnings: list[str] = []
    missing: dict[str, int] = {}
    extra: dict[str, int] = {}

    for kind in KINDS:
        difference = pdf_counts[kind] - tex_counts[kind]
        if difference > 0:
            missing[kind] = difference
            warnings.append(
                f"PDF shows {pdf_counts[kind]} {kind}(s), but the LaTeX contains "
                f"only {tex_counts[kind]}. {difference} may be missing."
            )
        elif difference < 0:
            extra[kind] = -difference
            warnings.append(
                f"LaTeX contains {-difference} more {kind}(s) than the PDF text "
                "layer. Check for duplicated material from overlapping slices."
            )

    if pdf_sections and pdf_sections != tex_sections:
        warnings.append(
            f"PDF text layer shows {pdf_sections} numbered section headings, "
            f"but the LaTeX contains {tex_sections} section-like headings."
        )

    missing_fragments = [
        plan.number for plan in plans if plan.kind == "content" and not plan.latex.strip()
    ]
    if missing_fragments:
        warnings.append(
            "No LaTeX fragment was produced for content page(s): "
            + ", ".join(map(str, missing_fragments))
        )

    return {
        "pdf_headings": pdf_counts,
        "tex_headings": tex_counts,
        "missing_headings": missing,
        "extra_headings": extra,
        "pdf_sections": pdf_sections,
        "tex_sections": tex_sections,
        "missing_fragments": missing_fragments,
        "warnings": warnings,
    }
