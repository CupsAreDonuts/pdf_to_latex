"""Compile individual fragments and the assembled document."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from ..exceptions import CompileError, DependencyError
from ..models import CompileResult
from ..pdf.info import pdf_page_count
from ..util import atomic_write_text, ensure_dir, run_command, tail_text, which_or_fail
from .preamble import FRAGMENT_PREAMBLE


class LatexCompiler:
    def __init__(
        self,
        pdflatex: str = "pdflatex",
        timeout: int = 120,
        graphics_roots: Sequence[Path] | None = None,
    ) -> None:
        self.pdflatex = pdflatex
        self.timeout = timeout
        self.graphics_roots = list(graphics_roots or [])
        self.path = which_or_fail(pdflatex)

    def compile_fragment(
        self, fragment: str, dest_dir: Path, name: str = "fragment"
    ) -> CompileResult:
        ensure_dir(dest_dir)
        tex_path = dest_dir / f"{name}.tex"
        document = (
            FRAGMENT_PREAMBLE
            + self._graphicspath_command()
            + "\n\\begin{document}\n"
            + fragment.strip()
            + "\n\\end{document}\n"
        )
        atomic_write_text(tex_path, document)
        return self._compile(tex_path, runs=1)

    def _graphicspath_command(self) -> str:
        """Let fragments find figures relative to the build root.

        Fragment sources are compiled in their own directory, while their
        ``\\includegraphics`` paths are relative to the assembled document.
        The command is only injected into throwaway validation documents, not
        into the delivered ``.tex``.
        """
        if not self.graphics_roots:
            return ""
        roots = "".join(
            "{" + root.as_posix().rstrip("/") + "/" + "}"
            for root in self.graphics_roots
        )
        return f"\n\\graphicspath{{{roots}}}\n"

    def compile_document(self, tex_path: Path, *, runs: int = 2) -> CompileResult:
        if not tex_path.exists():
            raise CompileError(f"TeX file does not exist: {tex_path}")
        return self._compile(tex_path, runs=runs)

    def _compile(self, tex_path: Path, *, runs: int) -> CompileResult:
        cwd = tex_path.parent
        combined: list[str] = []
        for _ in range(max(1, runs)):
            try:
                proc = run_command(
                    [
                        self.path,
                        "-interaction=nonstopmode",
                        "-halt-on-error",
                        "-file-line-error",
                        tex_path.name,
                    ],
                    cwd=cwd,
                    timeout=self.timeout,
                )
            except DependencyError:
                raise
            combined.append(proc.stdout or "")
            combined.append(proc.stderr or "")
            log_path = tex_path.with_suffix(".log")
            if log_path.exists():
                combined.append(log_path.read_text(encoding="utf-8", errors="replace"))
            if proc.returncode != 0:
                return CompileResult(
                    ok=False,
                    log=tail_text("\n".join(combined), lines=80, chars=12000),
                    pdf_path=None,
                    pages=None,
                )

        pdf_path = tex_path.with_suffix(".pdf")
        return CompileResult(
            ok=pdf_path.exists(),
            log=tail_text("\n".join(combined), lines=80, chars=12000),
            pdf_path=pdf_path if pdf_path.exists() else None,
            pages=pdf_page_count(pdf_path),
        )
