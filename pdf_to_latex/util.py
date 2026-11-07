"""Small, dependency-free helpers used across the pipeline."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Iterable, Sequence

from .exceptions import DependencyError, PipelineError


def which_or_fail(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise DependencyError(
            f"Required program '{name}' was not found on PATH. "
            "Install it (poppler-utils for pdfinfo/pdftotext/pdftoppm, "
            "TeX Live for pdflatex) and try again."
        )
    return path


def run_command(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command and return its completed process.

    A missing executable is a dependency error; a timeout is a pipeline error.
    Callers can inspect ``returncode`` and output.
    """
    try:
        return subprocess.run(
            list(command),
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise DependencyError(f"Executable not found: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PipelineError(
            f"Command timed out after {timeout}s: {' '.join(command)}"
        ) from exc


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    path = Path(path)
    ensure_dir(path.parent)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path = Path(path)
    ensure_dir(path.parent)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tail_text(text: str, lines: int = 40, chars: int = 6000) -> str:
    if not text:
        return ""
    tail = "\n".join(text.splitlines()[-lines:])
    return tail[-chars:]


def parse_page_spec(spec: str | None, page_count: int) -> list[int]:
    """Parse ``1-3,7,10-12`` into a sorted, de-duplicated list of pages."""
    if not spec:
        return list(range(1, page_count + 1))

    selected: set[int] = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start_s, end_s = chunk.split("-", 1)
            try:
                start, end = int(start_s), int(end_s)
            except ValueError as exc:
                raise PipelineError(f"Invalid page range: {chunk!r}") from exc
            if start > end:
                start, end = end, start
            selected.update(range(start, end + 1))
        else:
            try:
                selected.add(int(chunk))
            except ValueError as exc:
                raise PipelineError(f"Invalid page number: {chunk!r}") from exc

    invalid = sorted(page for page in selected if page < 1 or page > page_count)
    if invalid:
        raise PipelineError(
            f"Page(s) {invalid} are outside the PDF range 1-{page_count}."
        )
    if not selected:
        raise PipelineError("Page selection is empty.")
    return sorted(selected)


def subtract_pages(pages: Iterable[int], skip_spec: str | None, page_count: int) -> list[int]:
    if not skip_spec:
        return sorted(set(pages))
    skipped = set(parse_page_spec(skip_spec, page_count))
    return sorted(set(pages) - skipped)


def strip_code_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^\s*```(?:latex|tex)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    # Remove stray fence-only lines in the middle.
    lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
    return "\n".join(lines).strip()


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def format_seconds(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}m {rest:.0f}s"


class Timer:
    def __init__(self) -> None:
        self.started = time.monotonic()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started
