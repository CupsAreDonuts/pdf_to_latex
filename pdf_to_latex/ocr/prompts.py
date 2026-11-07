"""Prompt construction for math-aware page transcription."""

from __future__ import annotations

PROMPT_VERSION = "2026-11-03.2"

_RULES = r"""
You are a meticulous mathematical typesetting engine. Convert the visible
content of the page image into a LaTeX fragment.

Output rules:
- Return only the LaTeX fragment. No Markdown code fences, no explanation, no
  preamble, no commentary.
- Transcribe every visible prose line and every formula in reading order.
- Do not add proofs, summaries, interpretations, or material that is not
  visible in the image. This is a transcription task, not a proof task.
- Ignore running headers, running footers, and page numbers.
- Preserve the document's language and mathematical notation.
- Use \chapter{...}, \section{...}, \subsection{...}, \subsubsection{...}
  for headings. Do not include the printed heading numbers; LaTeX numbers
  headings itself.
- Use these environments for theorem-like items: theorem, definition, lemma,
  corollary, proposition, example, remark, exercise, proof. Do not include the
  printed number in the environment. Put it in a comment immediately before
  the environment, for example:
      % original-number: 1.1
      \begin{theorem}
      ...
      \end{theorem}
  If the item has a parenthetical title, use the optional argument:
      \begin{theorem}[A descriptive title]
- Use amsmath/amssymb constructs: $...$, \[...\], align, cases, pmatrix,
  \mathbb, \mathcal, \operatorname, etc.
- For a table-of-contents page, output only \tableofcontents.
- For a title page, use \begin{titlepage}...\end{titlepage}.
- If a page is blank, output nothing.
- If a symbol or word is genuinely unreadable, write \ocruncertain{...} and
  add a comment % OCR-UNCERTAIN near it. Do not guess silently.
- Do not wrap the fragment in \documentclass, \begin{document}, or
  \end{document}.
- Do not use \includegraphics for the page image.
""".strip()


def build_prompt(
    *,
    page_text: str,
    page_number: int,
    total_pages: int,
    slice_index: int = 0,
    slice_count: int = 1,
    previous_latex: str | None = None,
    compile_log: str | None = None,
    strict: bool = False,
) -> str:
    """Build the user prompt for one page or one vertical slice."""
    parts = [_RULES, ""]

    if slice_count > 1:
        parts.append(
            f"This image is vertical slice {slice_index} of {slice_count} of "
            f"PDF page {page_number} (page {page_number} of {total_pages}). "
            "Transcribe only what is visible in this slice. Do not repeat "
            "material from other slices."
        )
    else:
        parts.append(
            f"This is PDF page {page_number} of {total_pages}. Transcribe the "
            "entire visible page."
        )

    if strict:
        parts.append(
            "A previous attempt was incomplete or structurally wrong. Be "
            "especially careful to transcribe every line and to use the "
            "requested theorem-like environments."
        )

    if previous_latex:
        parts.extend(
            [
                "",
                "The previous attempt produced the following LaTeX, which did "
                "not compile or was incomplete. Repair it while preserving all "
                "visible content:",
                "----- BEGIN PREVIOUS ATTEMPT -----",
                previous_latex[:9000],
                "----- END PREVIOUS ATTEMPT -----",
            ]
        )
    if compile_log:
        parts.extend(
            [
                "",
                "Compiler log (truncated):",
                "----- BEGIN LOG -----",
                compile_log[-5000:],
                "----- END LOG -----",
            ]
        )

    if page_text.strip():
        parts.extend(
            [
                "",
                "Text-layer hint. It may contain OCR artifacts, especially in "
                "mathematics. Use it only for prose, line order, and names; the "
                "image is authoritative for every formula:",
                "----- BEGIN TEXT HINT -----",
                page_text[:9000],
                "----- END TEXT HINT -----",
            ]
        )
    else:
        parts.append(
            "\nThere is no usable text layer for this page. Read everything "
            "from the image."
        )

    return "\n".join(parts)
