"""Prompt construction for math-aware page transcription."""

from __future__ import annotations

PROMPT_VERSION = "2026-11-08.1"

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
""".strip()

_FIGURE_RULES = r"""
Figures and artwork:
- Do not redraw figures, diagrams, plots, or photographs, and do not use TikZ
  or pgfplots. Preserve the original artwork instead.
- For every figure, write a marker comment immediately before its figure
  environment:
      % FIG-BOX <n>: x0,y0,x1,y1
  <n> starts at 1 on the image you were given. Coordinates are integers from
  0 to 1000 measured from the top-left corner of the image: (x0,y0) is the
  top-left corner and (x1,y1) the bottom-right corner of the artwork. Do not
  include the printed caption in the box; transcribe the caption separately.
- Put the artwork in a figure environment where it appears and use
  \includegraphics[width=0.8\linewidth]{FIG:<n>} with the same number:
      % FIG-BOX 1: 120,340,880,620
      \begin{figure}[htbp]
        \centering
        \includegraphics[width=0.8\linewidth]{FIG:1}
        \caption{...}
      \end{figure}
  The pipeline replaces FIG:<n> with the cropped artwork.
- If you cannot estimate a box, still emit \includegraphics{FIG:<n>} without a
  FIG-BOX comment; the whole page will be used.
- Never include the whole page image as a figure.
""".strip()

_NO_FIGURE_RULES = r"""
- Do not use \includegraphics and do not attempt to redraw figures. Transcribe
  text and formulas only.
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
    include_figures: bool = True,
) -> str:
    """Build the user prompt for one page or one vertical slice."""
    parts = [_RULES, ""]
    parts.append(_FIGURE_RULES if include_figures else _NO_FIGURE_RULES)
    parts.append("")

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
