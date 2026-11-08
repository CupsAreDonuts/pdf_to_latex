"""End-to-end PDF -> LaTeX orchestration."""

from __future__ import annotations

import json
import logging
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .config import Context, Settings
from .exceptions import ApiError, CompileError, ConfigError, PipelineError
from .latex.assemble import assemble_document
from .latex.compile import LatexCompiler
from .models import CompileResult, OcrResult, PagePlan, PageSlice
from .ocr.cache import ResponseCache
from .ocr.client import DeepSeekClient
from .ocr.sanitize import extract_uncertain, sanitize_latex
from .pdf.figures import (
    FigureExtraction,
    FigureExtractor,
    discard_figure_placeholders,
)
from .pdf.info import inspect_pdf
from .pdf.render import is_blank_image, render_page_image
from .pdf.slices import make_slices
from .pdf.text import (
    extract_all_text,
    extract_page_text,
    is_blank_text,
    looks_like_toc,
)
from .util import (
    Timer,
    atomic_write_text,
    ensure_dir,
    format_seconds,
    parse_page_spec,
    subtract_pages,
    tail_text,
    which_or_fail,
)
from .validate.prose import prose_recall, summarize_recall
from .validate.report import build_report, write_report
from .validate.structure import (
    count_pdf_headings,
    count_tex_headings,
    validate_structure,
)

LOGGER = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.ctx = Context(settings)
        self.cache = ResponseCache(
            self.ctx.cache_dir, enabled=not settings.no_cache
        )
        self.client = DeepSeekClient(settings, self.cache)
        self.compiler = LatexCompiler(
            pdflatex=settings.pdflatex,
            timeout=settings.compile_timeout,
            graphics_roots=[self.ctx.build_dir.resolve()],
        )
        self.figure_extractor = (
            FigureExtractor(
                pdf=settings.pdf,
                figures_dir=self.ctx.figures_dir,
                relative_dir=settings.figure_relpath,
                render_dir=self.ctx.pages_dir / "hires",
                dpi=settings.figure_dpi,
                padding=settings.figure_padding,
            )
            if settings.figures
            else None
        )
        self._delivery_warnings: list[str] = []
        self._timer = Timer()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def run(self) -> int:
        self._prepare()
        self.client.check_model()
        info = inspect_pdf(self.settings.pdf)
        pages = subtract_pages(
            parse_page_spec(self.settings.pages, info.pages),
            self.settings.skip_pages,
            info.pages,
        )
        if not pages:
            raise ConfigError("No pages left after applying --skip-pages.")

        LOGGER.info("PDF: %s (%s pages)", info.path, info.pages)
        LOGGER.info("Processing pages: %s", _compact_ranges(pages))
        LOGGER.info("Output bundle: %s", self.settings.bundle_dir)
        LOGGER.info("LaTeX file: %s", self.settings.tex_path)

        plans = self._build_plans(info, pages)
        self._process_plans(plans, info.pages)
        tex = assemble_document(plans)

        atomic_write_text(self.settings.tex_path, tex)
        main_tex = self.ctx.build_dir / "main.tex"
        atomic_write_text(main_tex, tex)

        full_compile = self.compiler.compile_document(main_tex, runs=2)
        self._prune_unused_figures(plans)
        self._deliver_bundle(full_compile)
        if not full_compile.ok:
            LOGGER.error("Full document did not compile. See %s", main_tex)
        else:
            LOGGER.info(
                "Full document compiled: %s (%s pages)",
                full_compile.pdf_path,
                full_compile.pages,
            )

        pdf_text = extract_all_text(self.settings.pdf)
        structure = validate_structure(pdf_text, tex, plans)
        prose = summarize_recall(
            [(plan.number, plan.prose_recall) for plan in plans],
            threshold=self.settings.min_prose_recall,
        )

        stats = self._collect_stats(plans)
        warnings = self._collect_warnings(plans, structure, full_compile)
        report = build_report(
            pdf_path=self.settings.pdf,
            pdf_pages=info.pages,
            output_path=self.settings.tex_path,
            model=self.settings.model,
            plans=plans,
            full_compile_ok=full_compile.ok,
            full_compile_pages=full_compile.pages,
            full_compile_log=full_compile.log,
            structure=structure,
            prose=prose,
            usage=stats,
            warnings=warnings,
        )
        self._write_manifest(info, plans, pages)
        json_report, md_report = write_report(self.ctx.build_dir.parent, report)

        self._print_summary(plans, stats, full_compile, warnings, json_report, md_report)

        if not full_compile.ok:
            return 1
        if structure.get("missing_fragments"):
            return 1
        if self._delivery_warnings:
            return 1
        if self.settings.strict and warnings:
            return 1
        return 0

    # ------------------------------------------------------------------
    # Preparation
    # ------------------------------------------------------------------
    def _prepare(self) -> None:
        for program in ("pdfinfo", "pdftotext", "pdftoppm", "pdflatex"):
            which_or_fail(program)

        if not self.settings.output.name:
            raise ConfigError("--output must name a directory or a .tex file.")
        if (
            self.settings.bundle_dir.exists()
            and not self.settings.bundle_dir.is_dir()
        ):
            raise ConfigError(
                f"Output bundle is not a directory: {self.settings.bundle_dir}"
            )
        if (
            self.settings.output.exists()
            and self.settings.output.is_file()
            and self.settings.output.suffix.lower() != ".tex"
        ):
            raise ConfigError(
                f"--output must be a directory or a .tex file: {self.settings.output}"
            )
        if self.settings.tex_path.exists() and not self.settings.force:
            raise ConfigError(
                f"Output already exists: {self.settings.tex_path}. "
                "Pass --force to overwrite it."
            )
        if self.settings.pdf.resolve() == self.settings.tex_path.resolve():
            raise ConfigError("--pdf and --output must be different files.")
        delivered_pdf = self.settings.tex_path.with_suffix(".pdf")
        if self.settings.pdf.resolve() == delivered_pdf.resolve():
            raise ConfigError(
                "--pdf must not be the PDF that is delivered inside the output bundle."
            )
        if self.settings.figure_dpi <= 0:
            raise ConfigError("--figure-dpi must be positive.")
        if not 0.0 <= self.settings.figure_padding < 0.5:
            raise ConfigError("--figure-padding must be between 0 and 0.5.")

        if self.settings.clean_workdir and self.settings.workdir.exists():
            shutil.rmtree(self.settings.workdir)
        ensure_dir(self.settings.bundle_dir)
        for directory in (
            self.ctx.pages_dir,
            self.ctx.text_dir,
            self.ctx.cache_dir,
            self.ctx.fragments_dir,
            self.ctx.build_dir,
            self.ctx.figures_dir,
            self.ctx.logs_dir,
        ):
            ensure_dir(directory)

        atomic_write_text(
            self.settings.workdir / "settings.json",
            json.dumps(_jsonable(asdict(self.settings)), indent=2) + "\n",
        )

    # ------------------------------------------------------------------
    # Output bundle
    # ------------------------------------------------------------------
    def _prune_unused_figures(self, plans: list[PagePlan]) -> None:
        """Drop staged crops that the delivered document does not reference."""
        if not self.ctx.figures_dir.exists():
            return
        referenced: set[str] = set()
        for plan in plans:
            referenced.update(
                Path(figure.path).name for figure in plan.figures if figure.path
            )
            referenced.update(
                Path(match).name
                for match in re.findall(r"figures/[^}\s]+", plan.latex)
            )
        try:
            for path in self.ctx.figures_dir.iterdir():
                if path.is_file() and path.name not in referenced:
                    path.unlink()
        except OSError as exc:
            LOGGER.warning("Could not prune unused figure files: %s", exc)

    def _deliver_bundle(self, full_compile: CompileResult) -> None:
        """Mirror figures and the compiled PDF next to the delivered .tex."""
        target = (
            self.settings.bundle_dir
            / "figures"
            / self.settings.figure_namespace
        )
        try:
            if target.exists():
                shutil.rmtree(target)
            if any(path.is_file() for path in self.ctx.figures_dir.rglob("*")):
                shutil.copytree(self.ctx.figures_dir, target)
        except OSError as exc:
            self._delivery_warnings.append(
                f"Could not copy figures into the output bundle: {exc}"
            )

        pdf_target = self.settings.tex_path.with_suffix(".pdf")
        try:
            if full_compile.ok and full_compile.pdf_path is not None:
                if pdf_target.resolve() != self.settings.pdf.resolve():
                    shutil.copy2(full_compile.pdf_path, pdf_target)
            elif pdf_target.exists():
                # Do not leave a PDF from an earlier run beside a .tex that no
                # longer compiles.
                if pdf_target.resolve() != self.settings.pdf.resolve():
                    pdf_target.unlink()
        except OSError as exc:
            self._delivery_warnings.append(
                f"Could not copy the compiled PDF into the output bundle: {exc}"
            )

    # ------------------------------------------------------------------
    # Planning / classification
    # ------------------------------------------------------------------
    def _build_plans(self, info: Any, pages: list[int]) -> list[PagePlan]:
        plans: list[PagePlan] = []
        previous_was_toc = False
        for index, page in enumerate(pages, start=1):
            LOGGER.info("Inspecting page %s (%s/%s)", page, index, len(pages))
            text = extract_page_text(info.path, page)
            text_path = self.ctx.text_dir / f"page-{page:04d}.txt"
            atomic_write_text(text_path, text + "\n")

            plan = PagePlan(number=page, text=text, text_path=text_path)
            if is_blank_text(text):
                image_path = render_page_image(
                    info.path,
                    page,
                    self.ctx.pages_dir,
                    dpi=self.settings.dpi,
                    max_width=self.settings.max_image_width,
                    jpeg_quality=self.settings.jpeg_quality,
                )
                plan.image_path = image_path
                plan.kind = "blank" if is_blank_image(image_path) else "content"
            elif looks_like_toc(text, previous_was_toc):
                plan.kind = "toc"
                plan.source = "toc"
            else:
                plan.kind = "content"
                plan.image_path = render_page_image(
                    info.path,
                    page,
                    self.ctx.pages_dir,
                    dpi=self.settings.dpi,
                    max_width=self.settings.max_image_width,
                    jpeg_quality=self.settings.jpeg_quality,
                )

            if plan.kind != "blank":
                previous_was_toc = plan.kind == "toc"
            plans.append(plan)
        return plans

    # ------------------------------------------------------------------
    # OCR + compilation
    # ------------------------------------------------------------------
    def _process_plans(self, plans: list[PagePlan], total_pages: int) -> None:
        content = [plan for plan in plans if plan.kind == "content"]
        if not content:
            return

        workers = max(1, min(self.settings.workers, len(content)))
        if workers == 1:
            for index, plan in enumerate(content, start=1):
                LOGGER.info("Processing page %s (%s/%s)", plan.number, index, len(content))
                self._process_one_safely(plan, total_pages)
            return

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self._process_one_safely, plan, total_pages): plan
                for plan in content
            }
            for index, future in enumerate(as_completed(futures), start=1):
                plan = futures[future]
                try:
                    future.result()
                except Exception as exc:  # defensive: worker records its own errors
                    plan.warnings.append(f"Unhandled worker error: {exc}")
                    plan.compile_ok = False
                LOGGER.info(
                    "Finished page %s (%s/%s)", plan.number, index, len(content)
                )

    def _process_one_safely(self, plan: PagePlan, total_pages: int) -> None:
        try:
            self._process_one(plan, total_pages)
        except Exception as exc:
            LOGGER.exception("Page %s failed", plan.number)
            plan.warnings.append(f"Page failed: {exc}")
            plan.compile_ok = False

    def _process_one(self, plan: PagePlan, total_pages: int) -> None:
        if plan.kind == "toc":
            plan.latex = "\\tableofcontents"
            plan.compile_ok = True
            return
        if plan.kind != "content" or plan.image_path is None:
            return

        full_error: ApiError | None = None
        if not self.settings.force_slices:
            try:
                latex = self._transcribe_image(
                    plan,
                    plan.image_path,
                    total_pages=total_pages,
                )
                extraction = self._resolve_figures(plan, latex, slice_=None)
                self._evaluate_and_adopt(plan, extraction.latex, extraction)
            except ApiError as exc:
                full_error = exc
                plan.warnings.append(f"Full-page OCR failed: {exc}")
                LOGGER.warning("Full-page OCR failed for page %s: %s", plan.number, exc)

        if not self._is_good(plan):
            self._try_slices(plan, total_pages)

        if not self._is_good(plan):
            self._try_repair(plan, total_pages, full_error)

        if not plan.latex.strip() or (
            not plan.figures and not _has_visible_latex(plan.latex)
        ):
            self._insert_page_image_fallback(plan)

        if not self._is_good(plan):
            plan.warnings.append(
                "Page is not fully validated; review the fragment and report."
            )

        if plan.latex.strip():
            atomic_write_text(
                self.ctx.fragments_dir / f"page-{plan.number:04d}.tex",
                plan.latex.strip() + "\n",
            )

    def _try_slices(self, plan: PagePlan, total_pages: int) -> None:
        try:
            slices = make_slices(
                plan.image_path,  # type: ignore[arg-type]
                self.ctx.pages_dir / "slices",
                plan.number,
                count=2,
                jpeg_quality=self.settings.jpeg_quality,
            )
        except Exception as exc:
            plan.warnings.append(f"Could not create page slices: {exc}")
            return
        if len(slices) < 2:
            plan.warnings.append("Page slicing produced no useful split.")
            return

        plan.slices = slices
        extractions: list[FigureExtraction] = []
        try:
            for item in slices:
                fragment = self._transcribe_image(
                    plan,
                    item.image_path,
                    slice_=item,
                    total_pages=total_pages,
                )
                extractions.append(
                    self._resolve_figures(plan, fragment, slice_=item)
                )
        except ApiError as exc:
            plan.warnings.append(f"Slice OCR failed: {exc}")
            return

        merged = _merge_extractions(extractions)
        if merged.latex.strip():
            self._evaluate_and_adopt(plan, merged.latex, merged)

    def _try_repair(
        self,
        plan: PagePlan,
        total_pages: int,
        previous_error: ApiError | None,
    ) -> None:
        if plan.image_path is None:
            return
        try:
            latex = self._transcribe_image(
                plan,
                plan.image_path,
                total_pages=total_pages,
                previous_latex=plan.latex,
                compile_log=plan.compile_log,
                strict=True,
            )
        except ApiError as exc:
            plan.warnings.append(f"Repair OCR failed: {exc}")
            if previous_error:
                plan.warnings.append(f"Earlier full-page error: {previous_error}")
            return
        extraction = self._resolve_figures(
            plan, latex, slice_=None, variant="repair"
        )
        self._evaluate_and_adopt(plan, extraction.latex, extraction)

    def _insert_page_image_fallback(self, plan: PagePlan) -> None:
        """Keep a content page in the document even when OCR produced nothing."""
        if self.figure_extractor is None:
            return
        extraction = self.figure_extractor.whole_page_fragment(
            plan.number, reason="OCR produced no LaTeX fragment"
        )
        if not extraction.latex:
            plan.warnings.extend(extraction.warnings)
            return
        self._evaluate_and_adopt(plan, extraction.latex, extraction, force=True)
        plan.source = "page-image"
        plan.warnings.append(
            "No LaTeX could be transcribed; the whole page image was inserted."
        )

    def _transcribe_image(
        self,
        plan: PagePlan,
        image_path: Path,
        *,
        slice_: PageSlice | None = None,
        total_pages: int,
        previous_latex: str | None = None,
        compile_log: str | None = None,
        strict: bool = False,
    ) -> str:
        slice_index = slice_.index if slice_ is not None else 0
        slice_count = slice_.count if slice_ is not None else 1
        result = self.client.transcribe(
            image_path=image_path,
            page_text=plan.text,
            page_number=plan.number,
            total_pages=total_pages,
            slice_index=slice_index,
            slice_count=slice_count,
            previous_latex=previous_latex,
            compile_log=compile_log,
            strict=strict,
        )
        self._record_usage(plan, result)
        if result.finish_reason == "length":
            plan.warnings.append(
                f"OCR output hit the token cap for slice {slice_index}; "
                "the fragment may be truncated."
            )
        return sanitize_latex(result.latex, page_number=plan.number)

    def _resolve_figures(
        self,
        plan: PagePlan,
        latex: str,
        *,
        slice_: PageSlice | None,
        variant: str = "",
    ) -> FigureExtraction:
        if self.figure_extractor is None:
            return discard_figure_placeholders(latex)
        return self.figure_extractor.resolve(
            page=plan.number,
            latex=latex,
            slice_=slice_,
            ocr_page_image=plan.image_path,
            variant=variant,
        )

    def _evaluate_and_adopt(
        self,
        plan: PagePlan,
        latex: str,
        extraction: FigureExtraction | None = None,
        *,
        force: bool = False,
    ) -> None:
        if not latex.strip():
            plan.warnings.append("Model returned an empty fragment.")
            return
        compile_result = self._compile_fragment(plan, latex)
        recall = prose_recall(plan.text, latex)

        current_ok = bool(plan.compile_ok)
        candidate_ok = bool(compile_result.ok)
        current_recall = plan.prose_recall if plan.prose_recall is not None else -1.0
        candidate_recall = recall if recall is not None else -1.0

        better = (
            force
            or not plan.latex.strip()
            or (candidate_ok and not current_ok)
            or (candidate_ok == current_ok and candidate_recall > current_recall + 0.02)
        )
        if not better:
            return

        plan.latex = latex
        plan.compile_ok = compile_result.ok
        plan.compile_log = compile_result.log
        plan.prose_recall = recall
        plan.uncertain = extract_uncertain(latex)
        plan.figures = list(extraction.figures) if extraction is not None else []
        if extraction is not None:
            plan.warnings.extend(extraction.warnings)

    def _compile_fragment(self, plan: PagePlan, latex: str) -> CompileResult:
        dest = self.ctx.fragments_dir / f"page-{plan.number:04d}"
        return self.compiler.compile_fragment(
            latex, dest, name=f"page-{plan.number:04d}"
        )

    def _is_good(self, plan: PagePlan) -> bool:
        if plan.compile_ok is not True:
            return False
        if (
            plan.prose_recall is not None
            and plan.prose_recall < self.settings.min_prose_recall
        ):
            return False
        if self._missing_expected_environments(plan):
            return False
        return True

    def _missing_expected_environments(self, plan: PagePlan) -> bool:
        if not plan.text.strip() or not plan.latex.strip():
            return False
        pdf_counts = count_pdf_headings(plan.text)
        tex_counts = count_tex_headings(plan.latex)
        return any(pdf_counts[kind] > tex_counts[kind] for kind in pdf_counts)

    def _record_usage(self, plan: PagePlan, result: OcrResult) -> None:
        plan.ocr_calls += 1
        if result.cached:
            plan.cached_calls += 1
        usage = result.usage or {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            plan.usage[key] = int(plan.usage.get(key, 0)) + int(usage.get(key, 0) or 0)
        reasoning = usage.get("completion_tokens_details", {}).get(
            "reasoning_tokens", 0
        )
        plan.usage["reasoning_tokens"] = int(plan.usage.get("reasoning_tokens", 0)) + int(
            reasoning or 0
        )

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    def _collect_stats(self, plans: list[PagePlan]) -> dict[str, int]:
        token_keys = (
            "prompt_tokens",
            "completion_tokens",
            "reasoning_tokens",
            "total_tokens",
        )
        stats = {key: 0 for key in token_keys}
        stats["ocr_calls"] = 0
        stats["cached_calls"] = 0
        stats["figures"] = 0
        stats["figure_page_fallbacks"] = 0
        for plan in plans:
            for key in token_keys:
                stats[key] += int(plan.usage.get(key, 0))
            stats["ocr_calls"] += plan.ocr_calls
            stats["cached_calls"] += plan.cached_calls
            stats["figures"] += len(plan.figures)
            stats["figure_page_fallbacks"] += sum(
                1 for figure in plan.figures if figure.source == "page"
            )
        return stats

    def _collect_warnings(
        self,
        plans: list[PagePlan],
        structure: dict[str, Any],
        full_compile: CompileResult,
    ) -> list[str]:
        warnings: list[str] = []
        for plan in plans:
            for warning in plan.warnings:
                warnings.append(f"Page {plan.number}: {warning}")
            if plan.uncertain:
                warnings.append(
                    f"Page {plan.number}: {len(plan.uncertain)} uncertain OCR token(s)."
                )
        warnings.extend(structure.get("warnings", []))
        warnings.extend(self._delivery_warnings)
        if not full_compile.ok:
            warnings.append("The assembled document did not compile; see the log tail.")
        else:
            warnings.extend(_compile_log_warnings(full_compile.log))
        return _dedupe(warnings)

    def _write_manifest(
        self, info: Any, plans: list[PagePlan], pages: list[int]
    ) -> None:
        manifest = {
            "pdf": {
                "path": str(self.settings.pdf),
                "pages": info.pages,
                "title": info.title,
                "page_width_pt": info.page_width_pt,
                "page_height_pt": info.page_height_pt,
            },
            "settings": _jsonable(asdict(self.settings)),
            "selected_pages": pages,
            "pages": [_page_manifest(plan) for plan in plans],
        }
        atomic_write_text(
            self.settings.workdir / "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )

    def _print_summary(
        self,
        plans: list[PagePlan],
        stats: dict[str, int],
        full_compile: CompileResult,
        warnings: list[str],
        json_report: Path,
        md_report: Path,
    ) -> None:
        content_pages = sum(1 for plan in plans if plan.kind == "content")
        toc_pages = sum(1 for plan in plans if plan.kind == "toc")
        blank_pages = sum(1 for plan in plans if plan.kind == "blank")
        LOGGER.info("")
        LOGGER.info("Summary")
        LOGGER.info("  content pages: %s", content_pages)
        LOGGER.info("  TOC pages replaced: %s", toc_pages)
        LOGGER.info("  blank pages skipped: %s", blank_pages)
        LOGGER.info("  OCR calls: %s (%s cache hits)", stats["ocr_calls"], stats["cached_calls"])
        LOGGER.info("  tokens: %s", stats["total_tokens"])
        LOGGER.info(
            "  figures: %s (%s whole-page fallbacks)",
            stats["figures"],
            stats["figure_page_fallbacks"],
        )
        LOGGER.info("  full compile: %s", "OK" if full_compile.ok else "FAILED")
        LOGGER.info("  warnings: %s", len(warnings))
        LOGGER.info("  report: %s", json_report)
        LOGGER.info("  report: %s", md_report)
        LOGGER.info("  elapsed: %s", format_seconds(self._timer.elapsed))


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _page_manifest(plan: PagePlan) -> dict[str, Any]:
    return {
        "number": plan.number,
        "kind": plan.kind,
        "source": plan.source,
        "text_path": str(plan.text_path) if plan.text_path else None,
        "image_path": str(plan.image_path) if plan.image_path else None,
        "slices": [
            {
                "index": item.index,
                "count": item.count,
                "y0": item.y0,
                "y1": item.y1,
                "image_path": str(item.image_path),
            }
            for item in plan.slices
        ],
        "compile_ok": plan.compile_ok,
        "prose_recall": plan.prose_recall,
        "ocr_calls": plan.ocr_calls,
        "cached_calls": plan.cached_calls,
        "uncertain": plan.uncertain,
        "figures": [
            {
                "identifier": figure.identifier,
                "source": figure.source,
                "path": figure.path,
                "box": list(figure.box) if figure.box is not None else None,
                "reason": figure.reason,
            }
            for figure in plan.figures
        ],
        "warnings": plan.warnings,
    }


def _merge_extractions(extractions: list[FigureExtraction]) -> FigureExtraction:
    """Combine per-slice figure resolutions into one page fragment."""
    return FigureExtraction(
        latex="\n\n".join(item.latex for item in extractions if item.latex.strip()),
        figures=[figure for item in extractions for figure in item.figures],
        warnings=[warning for item in extractions for warning in item.warnings],
    )


_NON_CONTENT_COMMAND_RE = re.compile(
    r"\\(?:clearpage|newpage|pagebreak|tableofcontents|maketitle"
    r"|frontmatter|mainmatter|backmatter|vfill|hfill"
    r"|bigskip|medskip|smallskip|noindent|indent|null|relax|sloppy|fussy)\b"
)
_ARGUMENT_COMMAND_RE = re.compile(
    r"\\(?:vspace|hspace|thispagestyle|pagestyle)\*?\s*\{[^{}]*\}"
)
_EMPTY_ENVIRONMENT_RE = re.compile(r"\\begin\{([^{}]*)\}\s*\\end\{\1\}")


def _has_visible_latex(latex: str) -> bool:
    """True when a fragment contains something other than layout commands."""
    text = re.sub(r"(?m)(?<!\\)%.*$", "", latex)
    text = _ARGUMENT_COMMAND_RE.sub("", text)
    for _ in range(3):
        stripped = _EMPTY_ENVIRONMENT_RE.sub("", text)
        if stripped == text:
            break
        text = stripped
    text = _NON_CONTENT_COMMAND_RE.sub("", text)
    return bool(text.strip())


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _compact_ranges(pages: list[int]) -> str:
    if not pages:
        return ""
    ranges: list[str] = []
    start = previous = pages[0]
    for page in pages[1:]:
        if page == previous + 1:
            previous = page
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = page
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ", ".join(ranges)


def _compile_log_warnings(log: str) -> list[str]:
    warnings: list[str] = []
    patterns = (
        "undefined references",
        "Citation",
        "multiply defined",
        "Label(s) may have changed",
    )
    for line in log.splitlines():
        if any(pattern.lower() in line.lower() for pattern in patterns):
            cleaned = line.strip()
            if cleaned and cleaned not in warnings:
                warnings.append(cleaned)
    return warnings[:12]
