from __future__ import annotations

import unittest
from pathlib import Path

from pdf_to_latex.config import Context, Settings


def _settings(output: Path) -> Settings:
    return Settings(pdf=Path("input.pdf"), output=output, workdir=Path(".work"))


class OutputLayoutTests(unittest.TestCase):
    def test_tex_output_creates_a_bundle_directory(self) -> None:
        settings = _settings(Path("out/book.tex"))
        self.assertEqual(settings.bundle_dir, Path("out/book"))
        self.assertEqual(settings.tex_path, Path("out/book/book.tex"))
        self.assertEqual(settings.figure_namespace, "book")
        self.assertEqual(settings.figure_relpath, "figures/book")

    def test_directory_output_names_the_tex_after_the_directory(self) -> None:
        settings = _settings(Path("out/book"))
        self.assertEqual(settings.bundle_dir, Path("out/book"))
        self.assertEqual(settings.tex_path, Path("out/book/book.tex"))

    def test_uppercase_tex_suffix_is_recognised(self) -> None:
        settings = _settings(Path("out/book.TEX"))
        self.assertEqual(settings.bundle_dir, Path("out/book"))
        self.assertEqual(settings.tex_path, Path("out/book/book.TEX"))

    def test_figure_namespace_is_filesystem_safe(self) -> None:
        settings = _settings(Path("out/My Book"))
        self.assertEqual(settings.figure_namespace, "My_Book")

    def test_context_stages_figures_under_the_build_root(self) -> None:
        settings = _settings(Path("out/book"))
        context = Context(settings)
        self.assertEqual(
            context.figures_dir,
            Path(".work/build/figures/book"),
        )


if __name__ == "__main__":
    unittest.main()
