"""A conservative, general-purpose preamble for reconstructed documents."""

from __future__ import annotations

DOCUMENT_PREAMBLE = r"""
\documentclass[11pt,a4paper]{book}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{lmodern}
\usepackage{amsmath,amssymb,amsthm}
\usepackage{mathtools}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{array}
\usepackage{longtable}
\usepackage{enumitem}
\usepackage[margin=25mm]{geometry}
\usepackage{hyperref}

\setcounter{secnumdepth}{3}
\setcounter{tocdepth}{3}

\newcommand{\ocruncertain}[1]{\textbf{[OCR? #1]}}
\newcommand{\proofgap}[1]{\textbf{[PROOF GAP: #1]}}
\newcommand{\figureplaceholder}[1]{\fbox{\textit{[figure #1 unavailable]}}}

\theoremstyle{plain}
\newtheorem{theorem}{Theorem}[chapter]
\newtheorem{lemma}[theorem]{Lemma}
\newtheorem{corollary}[theorem]{Corollary}
\newtheorem{proposition}[theorem]{Proposition}

\theoremstyle{definition}
\newtheorem{definition}[theorem]{Definition}
\newtheorem{example}{Example}[chapter]
\newtheorem{exercise}{Exercise}[chapter]

\theoremstyle{remark}
\newtheorem{remark}{Remark}[chapter]

\hypersetup{
  colorlinks=true,
  linkcolor=blue,
  citecolor=blue,
  urlcolor=blue,
  bookmarksnumbered=true
}
""".strip()

FRAGMENT_PREAMBLE = DOCUMENT_PREAMBLE
