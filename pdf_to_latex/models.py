"""Small data objects shared by the pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PdfInfo:
    path: Path
    pages: int
    title: str | None = None
    page_width_pt: float | None = None
    page_height_pt: float | None = None
    raw: dict[str, str] = field(default_factory=dict)


@dataclass
class PageSlice:
    page: int
    index: int
    count: int
    y0: int
    y1: int
    image_path: Path


@dataclass
class PagePlan:
    number: int
    text: str = ""
    kind: str = "content"  # content, blank, toc
    image_path: Path | None = None
    text_path: Path | None = None
    slices: list[PageSlice] = field(default_factory=list)
    latex: str = ""
    compile_ok: bool | None = None
    compile_log: str = ""
    prose_recall: float | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    ocr_calls: int = 0
    cached_calls: int = 0
    warnings: list[str] = field(default_factory=list)
    uncertain: list[str] = field(default_factory=list)
    source: str = "ocr"  # ocr, toc, blank

    @property
    def is_content(self) -> bool:
        return self.kind == "content"


@dataclass
class OcrResult:
    latex: str
    reasoning: str | None
    usage: dict[str, Any]
    finish_reason: str | None
    cached: bool = False


@dataclass
class CompileResult:
    ok: bool
    log: str
    pdf_path: Path | None = None
    pages: int | None = None
