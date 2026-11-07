"""Content-addressed cache for expensive vision API calls."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..util import atomic_write_text, ensure_dir, sha256_text


class ResponseCache:
    def __init__(self, root: Path, *, enabled: bool = True) -> None:
        self.root = ensure_dir(root)
        self.enabled = enabled

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        path = self._path(key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def put(self, key: str, value: dict[str, Any]) -> None:
        if not self.enabled:
            return
        path = self._path(key)
        atomic_write_text(
            path,
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        )


def make_cache_key(
    *,
    model: str,
    prompt: str,
    image_sha256: str,
    max_tokens: int,
    reasoning_effort: str,
) -> str:
    return sha256_text(
        "\n".join(
            [
                "pdf-to-latex-cache-v1",
                model,
                str(max_tokens),
                reasoning_effort,
                image_sha256,
                sha256_text(prompt),
            ]
        )
    )
