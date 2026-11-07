"""Clean up model output and extract plain text for validation."""

from __future__ import annotations

import re

from ..util import strip_code_fences

_ENVIRONMENTS = (
    "theorem",
    "definition",
    "lemma",
    "corollary",
    "proposition",
    "example",
    "remark",
    "exercise",
    "proof",
)

_ALIASES = {
    "thm": "theorem",
    "defn": "definition",
    "def": "definition",
    "lem": "lemma",
    "cor": "corollary",
    "prop": "proposition",
    "ex": "example",
    "rem": "remark",
    "exe": "exercise",
}


def sanitize_latex(text: str, *, page_number: int | None = None) -> str:
    """Make a model response safe to wrap in a LaTeX document."""
    text = strip_code_fences(text)
    text = _strip_document_wrapper(text)
    text = _strip_page_number(text, page_number)
    text = _normalize_environment_names(text)
    text = _normalize_heading_stars(text)
    text = _merge_chapter_title_sections(text)
    text = _remove_printed_optional_numbers(text)
    text = text.replace("**", "")
    # A model sometimes emits a bare language label after a fence.
    text = re.sub(r"(?im)^\s*(?:latex|tex)\s*$", "", text)
    return text.strip()


def _strip_document_wrapper(text: str) -> str:
    begin = re.search(r"\\begin\s*\{document\}", text)
    end = re.search(r"\\end\s*\{document\}", text)
    if begin:
        text = text[begin.end() : end.start() if end else len(text)]

    text = re.sub(
        r"(?m)^\s*\\(?:documentclass|usepackage|RequirePackage)"
        r"(?:\s*\[[^\]]*\])?\s*\{[^{}]*\}\s*$",
        "",
        text,
    )
    text = re.sub(r"\\begin\s*\{document\}|\\end\s*\{document\}", "", text)
    return text


def _strip_page_number(text: str, page_number: int | None) -> str:
    if page_number is None:
        return text

    number = re.escape(str(page_number))
    text = re.sub(rf"(?m)^\s*{number}\s*$", "", text)
    text = re.sub(
        rf"\\begin\s*\{{center\}}\s*{number}\s*\\end\s*\{{center\}}",
        "",
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        rf"\\begin\s*\{{center\}}\s*\\thepage\s*\\end\s*\{{center\}}",
        "",
        text,
    )
    return text


def _normalize_environment_names(text: str) -> str:
    for name in _ENVIRONMENTS:
        text = re.sub(
            rf"\\begin\s*\{{\s*{name.capitalize()}\s*\}}",
            rf"\\begin{{{name}}}",
            text,
        )
        text = re.sub(
            rf"\\end\s*\{{\s*{name.capitalize()}\s*\}}",
            rf"\\end{{{name}}}",
            text,
        )
    for alias, name in _ALIASES.items():
        text = re.sub(
            rf"\\begin\s*\{{\s*{alias}\s*\}}",
            rf"\\begin{{{name}}}",
            text,
        )
        text = re.sub(
            rf"\\end\s*\{{\s*{alias}\s*\}}",
            rf"\\end{{{name}}}",
            text,
        )
    return text


def _normalize_heading_stars(text: str) -> str:
    # ``\section*{1.1 Title}`` -> ``\section{Title}``.  The printed number is
    # not needed because LaTeX numbers headings itself.
    for command in ("chapter", "section", "subsection", "subsubsection"):
        text = re.sub(
            rf"\\{command}\*\{{(\s*(?:Chapter\s+)?)\d+(?:\.\d+)*\s+"
            rf"(?=[^{{}}]*\}})",
            rf"\\{command}{{",
            text,
            flags=re.IGNORECASE,
        )
    return text


def _merge_chapter_title_sections(text: str) -> str:
    """Handle the common model pattern ``\chapter*{Chapter 1}`` + title section."""
    pattern = (
        r"\\chapter\*\{\s*(?:Chapter\s+)?\d+\s*\}\s*"
        r"\\section\*?\{\s*(.+?)\s*\}"
    )
    return re.sub(pattern, r"\\chapter{\1}", text, flags=re.DOTALL)


def _remove_printed_optional_numbers(text: str) -> str:
    names = "|".join(_ENVIRONMENTS)
    text = re.sub(
        rf"\\begin\{{({names})\}}\[\s*\d+(?:\.\d+)*\.?\s*\]",
        r"\\begin{\1}",
        text,
    )
    text = re.sub(
        rf"\\begin\{{({names})\}}\{{\s*\d+(?:\.\d+)*\.?\s*\}}",
        r"\\begin{\1}",
        text,
    )
    return text


def extract_uncertain(latex: str) -> list[str]:
    found = re.findall(r"\\ocruncertain\s*\{([^{}]*)\}", latex)
    found.extend(
        re.findall(r"(?im)(?<!\\)%\s*OCR-UNCERTAIN\s*:?\s*(.*)$", latex)
    )
    return [item.strip() for item in found if item.strip()]


def latex_to_plain_text(latex: str) -> str:
    """Approximate plain text for prose-recall checks."""
    text = re.sub(r"(?<!\\)%.*$", " ", latex, flags=re.MULTILINE)
    text = re.sub(r"\\ocruncertain\s*\{([^{}]*)\}", r" \1 ", text)
    text = re.sub(r"\\(?:begin|end)\s*\{[^{}]*\}", " ", text)
    text = re.sub(r"\\item\b", " ", text)

    # Keep the textual argument of common formatting commands.
    for command in (
        "chapter",
        "section",
        "subsection",
        "subsubsection",
        "paragraph",
        "textbf",
        "textit",
        "textsl",
        "textsc",
        "textrm",
        "textsf",
        "texttt",
        "emph",
        "text",
        "mathrm",
        "mathbf",
        "mathbb",
        "mathcal",
        "operatorname",
        "caption",
    ):
        text = re.sub(
            rf"\\{command}\s*\{{([^{{}}]*)\}}", r" \1 ", text
        )

    # Peel off commands with optional and mandatory arguments.  Repeat because
    # arguments can contain other commands.
    for _ in range(5):
        text = re.sub(
            r"\\[a-zA-Z@]+\*?(?:\s*\[[^\]]*\])?(?:\s*\{[^{}]*\})?",
            " ",
            text,
        )

    text = re.sub(r"\\(?:\[|\]|\(|\))", " ", text)
    text = re.sub(r"\\[\\&%$#_{}]", " ", text)
    text = re.sub(r"[${}&~^_]", " ", text)
    text = text.replace("{", " ").replace("}", " ")
    return re.sub(r"\s+", " ", text).strip()


def content_words(text: str) -> set[str]:
    """Words useful for a recall check, ignoring numbers and short tokens."""
    return {
        word.lower()
        for word in re.findall(r"[^\W\d_]{3,}", text, flags=re.UNICODE)
    }
