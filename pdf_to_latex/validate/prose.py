"""Cheap prose-recall checks against the PDF text layer."""

from __future__ import annotations

from ..ocr.sanitize import content_words, latex_to_plain_text


def prose_recall(reference_text: str, latex_fragment: str) -> float | None:
    """Fraction of reference prose words that also occur in the LaTeX.

    This deliberately ignores formula symbols.  It is a guard against dropped
    paragraphs, not a proof of fidelity.
    """
    reference = content_words(reference_text)
    if len(reference) < 5:
        return None
    hypothesis = content_words(latex_to_plain_text(latex_fragment))
    if not hypothesis:
        return 0.0
    return len(reference & hypothesis) / len(reference)


def summarize_recall(
    values: list[tuple[int, float | None]], *, threshold: float
) -> dict[str, object]:
    present = [value for _, value in values if value is not None]
    if not present:
        return {
            "mean": None,
            "min": None,
            "low_pages": [],
            "threshold": threshold,
        }
    return {
        "mean": round(sum(present) / len(present), 4),
        "min": round(min(present), 4),
        "low_pages": [
            page for page, value in values if value is not None and value < threshold
        ],
        "threshold": threshold,
    }
