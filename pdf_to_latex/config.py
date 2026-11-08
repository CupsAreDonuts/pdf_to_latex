"""Runtime configuration for the conversion pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    pdf: Path
    output: Path
    workdir: Path

    # API
    model: str = "deepseek-flash"
    api_base: str = "https://api.deepseek.com"
    api_key_env: str = "DEEPSEEK_API_KEY"
    max_tokens: int = 16000
    max_tokens_cap: int = 32000
    reasoning_effort: str = "low"
    request_timeout: int = 240
    max_retries: int = 3
    skip_model_check: bool = False

    # Rendering / OCR
    dpi: int = 200
    max_image_width: int = 1600
    jpeg_quality: int = 88
    workers: int = 2
    force_slices: bool = False
    min_prose_recall: float = 0.70

    # Figures
    figures: bool = True
    figure_dpi: int = 300
    figure_padding: float = 0.02

    # Page selection
    pages: str | None = None
    skip_pages: str | None = None

    # Compilation
    compile_timeout: int = 120
    pdflatex: str = "pdflatex"

    # Behaviour
    no_cache: bool = False
    force: bool = False
    clean_workdir: bool = False
    keep_workdir: bool = True
    resume: bool = True
    retry_failed: bool = False
    strict: bool = False
    verbose: bool = False
    dry_run: bool = False

    @property
    def bundle_dir(self) -> Path:
        """Directory that receives the .tex, the .pdf and the figures."""
        if self.output.suffix.lower() == ".tex":
            return self.output.with_suffix("")
        return self.output

    @property
    def tex_path(self) -> Path:
        """Location of the delivered .tex inside the bundle directory."""
        if self.output.suffix.lower() == ".tex":
            return self.bundle_dir / self.output.name
        return self.bundle_dir / f"{self.output.name}.tex"

    @property
    def figure_namespace(self) -> str:
        """Filesystem- and LaTeX-safe directory name for this document's figures."""
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", self.bundle_dir.name).strip("._")
        return name or "document"

    @property
    def figure_relpath(self) -> str:
        """Path prefix written into the LaTeX (relative to the document root)."""
        return f"figures/{self.figure_namespace}"


@dataclass
class Context:
    """Mutable per-run paths and counters."""

    settings: Settings
    pages_dir: Path = field(init=False)
    text_dir: Path = field(init=False)
    cache_dir: Path = field(init=False)
    fragments_dir: Path = field(init=False)
    state_dir: Path = field(init=False)
    build_dir: Path = field(init=False)
    figures_dir: Path = field(init=False)
    partial_tex_path: Path = field(init=False)
    logs_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        root = self.settings.workdir
        self.pages_dir = root / "pages"
        self.text_dir = root / "text"
        self.cache_dir = root / "cache"
        self.fragments_dir = root / "fragments"
        self.state_dir = root / "state"
        self.build_dir = root / "build"
        self.partial_tex_path = self.build_dir / "partial.tex"
        self.logs_dir = root / "logs"
        # Figures are staged under the build root so that ``main.tex`` and the
        # per-page fragments can reference them with plain relative paths.
        self.figures_dir = self.build_dir / "figures" / self.settings.figure_namespace
