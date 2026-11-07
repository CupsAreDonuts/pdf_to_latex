"""Write human-readable and machine-readable conversion reports."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models import PagePlan
from ..util import atomic_write_text, ensure_dir


def build_report(
    *,
    pdf_path: Path,
    pdf_pages: int,
    output_path: Path,
    model: str,
    plans: list[PagePlan],
    full_compile_ok: bool,
    full_compile_pages: int | None,
    full_compile_log: str,
    structure: dict[str, Any],
    prose: dict[str, Any],
    usage: dict[str, int],
    warnings: list[str],
) -> dict[str, Any]:
    page_rows = []
    for plan in sorted(plans, key=lambda item: item.number):
        page_rows.append(
            {
                "page": plan.number,
                "kind": plan.kind,
                "source": plan.source,
                "compile_ok": plan.compile_ok,
                "prose_recall": plan.prose_recall,
                "ocr_calls": plan.ocr_calls,
                "cached_calls": plan.cached_calls,
                "slices": len(plan.slices),
                "uncertain": plan.uncertain,
                "warnings": plan.warnings,
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pdf": str(pdf_path),
        "pdf_pages": pdf_pages,
        "output": str(output_path),
        "model": model,
        "full_compile_ok": full_compile_ok,
        "full_compile_pages": full_compile_pages,
        "full_compile_log_tail": full_compile_log,
        "structure": structure,
        "prose": prose,
        "usage": usage,
        "warnings": warnings,
        "pages": page_rows,
    }


def write_report(workdir: Path, report: dict[str, Any]) -> tuple[Path, Path]:
    ensure_dir(workdir)
    json_path = workdir / "report.json"
    markdown_path = workdir / "report.md"
    atomic_write_text(
        json_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    atomic_write_text(markdown_path, _as_markdown(report))
    return json_path, markdown_path


def _as_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# PDF to LaTeX conversion report",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- PDF: `{report['pdf']}`",
        f"- Pages: {report['pdf_pages']}",
        f"- Output: `{report['output']}`",
        f"- Model: `{report['model']}`",
        f"- Full compile: {'OK' if report['full_compile_ok'] else 'FAILED'}",
        f"- Compiled pages: {report['full_compile_pages']}",
        "",
        "## Token usage",
        "",
    ]
    usage = report.get("usage", {})
    for key in (
        "prompt_tokens",
        "completion_tokens",
        "reasoning_tokens",
        "total_tokens",
        "ocr_calls",
        "cached_calls",
    ):
        lines.append(f"- {key}: {usage.get(key, 0)}")

    structure = report.get("structure", {})
    lines.extend(["", "## Structure", ""])
    lines.append(f"- PDF headings: `{structure.get('pdf_headings', {})}`")
    lines.append(f"- LaTeX headings: `{structure.get('tex_headings', {})}`")
    lines.append(f"- Missing headings: `{structure.get('missing_headings', {})}`")
    lines.append(f"- Extra headings: `{structure.get('extra_headings', {})}`")
    lines.append(
        f"- Sections: PDF {structure.get('pdf_sections')} / "
        f"LaTeX {structure.get('tex_sections')}"
    )

    prose = report.get("prose", {})
    lines.extend(["", "## Prose recall", ""])
    lines.append(f"- Mean: {prose.get('mean')}")
    lines.append(f"- Minimum: {prose.get('min')}")
    lines.append(f"- Threshold: {prose.get('threshold')}")
    lines.append(f"- Low pages: {prose.get('low_pages', [])}")

    lines.extend(["", "## Pages", ""])
    lines.append(
        "| page | kind | compile | recall | OCR calls | cached | slices | warnings |"
    )
    lines.append("|---:|---|---|---|---:|---:|---:|---|")
    for row in report.get("pages", []):
        warnings = "; ".join(row.get("warnings", [])) or ""
        lines.append(
            f"| {row['page']} | {row['kind']} | {row['compile_ok']} | "
            f"{row['prose_recall']} | {row['ocr_calls']} | {row['cached_calls']} | "
            f"{row['slices']} | {warnings} |"
        )

    lines.extend(["", "## Warnings", ""])
    warnings = report.get("warnings", [])
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- None")

    if report.get("full_compile_log_tail"):
        lines.extend(
            [
                "",
                "## Full compile log tail",
                "",
                "```text",
                report["full_compile_log_tail"],
                "```",
            ]
        )
    return "\n".join(lines) + "\n"
