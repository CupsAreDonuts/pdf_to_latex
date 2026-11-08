from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

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

    def test_fragments_find_figures_through_the_graphics_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            figures = root / "figures" / "doc"
            figures.mkdir(parents=True)
            Image.new("RGB", (120, 80), "black").save(figures / "p0001-f01.png")

            compiler = LatexCompiler(timeout=60, graphics_roots=[root])
            fragment = (
                "\\begin{figure}[htbp]\n\\centering\n"
                "\\includegraphics[width=2cm]{figures/doc/p0001-f01.png}\n"
                "\\end{figure}"
            )
            result = compiler.compile_fragment(
                fragment, root / "fragments", "page-0001"
            )
            self.assertTrue(result.ok, result.log)


if __name__ == "__main__":
    unittest.main()
