from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pdf_to_latex.latex.compile import LatexCompiler


class CompileTests(unittest.TestCase):
    def test_compiles_a_theorem_fragment(self) -> None:
        compiler = LatexCompiler(timeout=60)
        fragment = r"""
\chapter{Conditional expectations}
\section{The Hilbert space \(L^2\)}
\begin{theorem}
Let \(K\) be a closed subspace of \(L^2\).
\end{theorem}
\begin{proof}
This is a placeholder proof.
\end{proof}
"""
        with tempfile.TemporaryDirectory() as tmp:
            result = compiler.compile_fragment(fragment, Path(tmp), "fragment")
            self.assertTrue(result.ok, result.log)
            self.assertIsNotNone(result.pdf_path)
            self.assertEqual(result.pages, 1)


if __name__ == "__main__":
    unittest.main()
