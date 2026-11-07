"""Command-line interface for the PDF -> LaTeX pipeline."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__
from .config import Settings
from .exceptions import PipelineError
from .pipeline import Pipeline

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main",
        description=(
            "Convert a PDF into a compilable LaTeX document using a "
            "math-aware vision model. Proofs are not generated."
        ),
    )
    parser.add_argument("--pdf", required=True, type=Path, help="Input PDF file.")
    parser.add_argument(
        "--output", required=True, type=Path, help="Output .tex file (must end in .tex)."
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        default=None,
        help="Intermediate files and cache (default: .<output-stem>.work next to output).",
    )
    parser.add_argument(
        "--pages",
        default=None,
        help="Only process these pages, e.g. '1-5,8,10-12'.",
    )
    parser.add_argument(
        "--skip-pages",
        default=None,
        help="Skip these pages, e.g. '2,7'.",
    )
    parser.add_argument(
        "--model",
        default="deepseek-flash",
        help="Vision-capable model name (default: deepseek-flash).",
    )
    parser.add_argument(
        "--api-base",
        default="https://api.deepseek.com",
        help="OpenAI-compatible API base URL.",
    )
    parser.add_argument(
        "--api-key-env",
        default="DEEPSEEK_API_KEY",
        help="Environment variable holding the API key.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=16000,
        help="Initial output-token budget per OCR call (default: 16000).",
    )
    parser.add_argument(
        "--max-tokens-cap",
        type=int,
        default=32000,
        help="Maximum output-token budget after automatic increases.",
    )
    parser.add_argument(
        "--reasoning-effort",
        default="low",
        choices=("low", "high", "max"),
        help="Reasoning effort sent to the model (default: low).",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="Page rendering resolution (default: 200).",
    )
    parser.add_argument(
        "--max-image-width",
        type=int,
        default=1600,
        help="Maximum rendered image width in pixels (default: 1600).",
    )
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=88,
        help="JPEG quality for page images (default: 88).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=2,
        help="Concurrent OCR requests (default: 2).",
    )
    parser.add_argument(
        "--force-slices",
        action="store_true",
        help="Always transcribe pages as two vertical slices.",
    )
    parser.add_argument(
        "--min-prose-recall",
        type=float,
        default=0.70,
        help="Minimum prose-word recall before a page is considered suspect.",
    )
    parser.add_argument(
        "--compile-timeout",
        type=int,
        default=120,
        help="pdflatex timeout in seconds.",
    )
    parser.add_argument(
        "--pdflatex",
        default="pdflatex",
        help="pdflatex executable (default: pdflatex).",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable the OCR response cache.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing output file.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete an existing work directory before starting.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return a non-zero exit code for validation warnings.",
    )
    parser.add_argument(
        "--skip-model-check",
        action="store_true",
        help="Do not query /models to verify image-input support.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def settings_from_args(args: argparse.Namespace) -> Settings:
    output = args.output.expanduser()
    if args.workdir:
        workdir = args.workdir.expanduser()
    else:
        workdir = output.parent / f".{output.stem}.work"
    return Settings(
        pdf=args.pdf.expanduser(),
        output=output,
        workdir=workdir,
        model=args.model,
        api_base=args.api_base,
        api_key_env=args.api_key_env,
        max_tokens=args.max_tokens,
        max_tokens_cap=args.max_tokens_cap,
        reasoning_effort=args.reasoning_effort,
        dpi=args.dpi,
        max_image_width=args.max_image_width,
        jpeg_quality=args.jpeg_quality,
        workers=args.workers,
        force_slices=args.force_slices,
        min_prose_recall=args.min_prose_recall,
        compile_timeout=args.compile_timeout,
        pdflatex=args.pdflatex,
        pages=args.pages,
        skip_pages=args.skip_pages,
        no_cache=args.no_cache,
        force=args.force,
        clean_workdir=args.clean,
        strict=args.strict,
        skip_model_check=args.skip_model_check,
        verbose=args.verbose,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )
    try:
        return Pipeline(settings_from_args(args)).run()
    except PipelineError as exc:
        if args.verbose:
            LOGGER.exception("Pipeline failed")
        else:
            LOGGER.error("error: %s", exc)
        return 1
    except KeyboardInterrupt:
        LOGGER.error("Interrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
