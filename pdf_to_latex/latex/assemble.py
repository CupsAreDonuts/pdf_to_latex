"""Assemble per-page LaTeX fragments into one compilable document."""

from __future__ import annotations

from ..models import PagePlan
from .preamble import DOCUMENT_PREAMBLE


def assemble_document(plans: list[PagePlan]) -> str:
    """Return a complete ``main.tex`` for the collected page fragments."""
    parts: list[str] = [DOCUMENT_PREAMBLE, "\n\\begin{document}\n\n"]
    toc_written = False

    for plan in sorted(plans, key=lambda item: item.number):
        latex = plan.latex.strip()
        if not latex:
            continue

        parts.append(f"% ===== PDF page {plan.number} =====\n")
        if "\\tableofcontents" in latex:
            if toc_written:
                parts.append("% duplicate table of contents omitted\n")
            else:
                parts.append(latex + "\n\\clearpage\n")
                toc_written = True
        else:
            parts.append(latex + "\n\n")

    parts.append("\\end{document}\n")
    return "".join(parts)
