"""DeepSeek vision client with retries, token-budget recovery, and caching."""

from __future__ import annotations

import base64
import logging
import os
import time
from pathlib import Path
from typing import Any

import requests

from ..config import Settings
from ..exceptions import ApiError, ConfigError
from ..models import OcrResult
from ..util import sha256_file
from .cache import ResponseCache, make_cache_key
from .prompts import build_prompt

LOGGER = logging.getLogger(__name__)


class DeepSeekClient:
    def __init__(self, settings: Settings, cache: ResponseCache) -> None:
        self.settings = settings
        self.cache = cache
        self.api_key = os.environ.get(settings.api_key_env)
        if not self.api_key:
            raise ConfigError(
                f"Environment variable {settings.api_key_env} is not set. "
                "Export your DeepSeek API key before running the pipeline."
            )
        self.base_url = settings.api_base.rstrip("/")
        self._model_checked = False

    # ------------------------------------------------------------------
    # Model capability check
    # ------------------------------------------------------------------
    def check_model(self) -> None:
        if self.settings.skip_model_check or self._model_checked:
            return
        url = f"{self.base_url}/models"
        payload = self._get_json(url)
        models = payload.get("data", []) if isinstance(payload, dict) else []
        selected = next(
            (item for item in models if item.get("id") == self.settings.model),
            None,
        )
        if selected is None:
            available = ", ".join(str(item.get("id")) for item in models) or "none"
            raise ConfigError(
                f"Model {self.settings.model!r} is not listed by {self.base_url}. "
                f"Available models: {available}"
            )
        modalities = selected.get("input_modalities", [])
        if "image" not in modalities:
            raise ConfigError(
                f"Model {self.settings.model!r} does not accept image input "
                f"(input_modalities={modalities}). Use a vision model such as "
                "deepseek-flash, or pass --skip-model-check for a compatible "
                "OpenAI-style endpoint."
            )
        self._model_checked = True

    # ------------------------------------------------------------------
    # Public transcription API
    # ------------------------------------------------------------------
    def transcribe(
        self,
        *,
        image_path: Path,
        page_text: str,
        page_number: int,
        total_pages: int,
        slice_index: int = 0,
        slice_count: int = 1,
        previous_latex: str | None = None,
        compile_log: str | None = None,
        strict: bool = False,
        max_tokens: int | None = None,
    ) -> OcrResult:
        self.check_model()
        prompt = build_prompt(
            page_text=page_text,
            page_number=page_number,
            total_pages=total_pages,
            slice_index=slice_index,
            slice_count=slice_count,
            previous_latex=previous_latex,
            compile_log=compile_log,
            strict=strict,
        )
        image_sha = sha256_file(image_path)
        budget = max_tokens or self.settings.max_tokens

        # If the model runs out of output budget, retry with a larger budget.
        for attempt in range(3):
            effective_budget = min(budget, self.settings.max_tokens_cap)
            key = make_cache_key(
                model=self.settings.model,
                prompt=prompt,
                image_sha256=image_sha,
                max_tokens=effective_budget,
                reasoning_effort=self.settings.reasoning_effort,
            )
            cached = self.cache.get(key)
            if cached is not None:
                LOGGER.debug("Cache hit for page %s slice %s", page_number, slice_index)
                return OcrResult(
                    latex=cached.get("content", ""),
                    reasoning=cached.get("reasoning_content"),
                    usage=cached.get("usage", {}),
                    finish_reason=cached.get("finish_reason"),
                    cached=True,
                )

            payload = self._build_payload(
                prompt=prompt,
                image_path=image_path,
                max_tokens=effective_budget,
            )
            data = self._post_json(f"{self.base_url}/chat/completions", payload)
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            content = (message.get("content") or "").strip()
            reasoning = message.get("reasoning_content")
            finish_reason = choice.get("finish_reason")
            usage = data.get("usage") or {}

            if content:
                self.cache.put(
                    key,
                    {
                        "content": content,
                        "reasoning_content": reasoning,
                        "usage": usage,
                        "finish_reason": finish_reason,
                        "model": data.get("model", self.settings.model),
                    },
                )
                return OcrResult(
                    latex=content,
                    reasoning=reasoning,
                    usage=usage,
                    finish_reason=finish_reason,
                    cached=False,
                )

            reasoning_tokens = (
                usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)
            )
            LOGGER.warning(
                "Page %s slice %s returned empty content "
                "(finish=%s, reasoning_tokens=%s, budget=%s)",
                page_number,
                slice_index,
                finish_reason,
                reasoning_tokens,
                effective_budget,
            )
            if effective_budget >= self.settings.max_tokens_cap:
                break
            budget = min(effective_budget * 2, self.settings.max_tokens_cap)

        raise ApiError(
            f"Model returned no final content for page {page_number} "
            f"slice {slice_index} even after increasing the token budget. "
            "Try --max-tokens with a larger value or inspect the API response."
        )

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    def _build_payload(
        self, *, prompt: str, image_path: Path, max_tokens: int
    ) -> dict[str, Any]:
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        return {
            "model": self.settings.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{encoded}"
                            },
                        },
                    ],
                }
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
            "reasoning_effort": self.settings.reasoning_effort,
            "stream": False,
        }

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _get_json(self, url: str) -> dict[str, Any]:
        last_error = ""
        for attempt in range(self.settings.max_retries + 1):
            try:
                response = requests.get(
                    url,
                    headers=self._headers(),
                    timeout=self.settings.request_timeout,
                )
            except requests.RequestException as exc:
                last_error = str(exc)
                self._sleep(attempt)
                continue
            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError as exc:
                    raise ApiError(f"Invalid JSON from {url}: {response.text[:500]}") from exc
            if response.status_code in {429, 500, 502, 503, 504}:
                last_error = self._response_error(response)
                self._sleep(attempt, response)
                continue
            raise ApiError(self._response_error(response))
        raise ApiError(f"GET {url} failed after retries: {last_error}")

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        last_error = ""
        for attempt in range(self.settings.max_retries + 1):
            try:
                response = requests.post(
                    url,
                    headers=self._headers(),
                    json=payload,
                    timeout=self.settings.request_timeout,
                )
            except requests.RequestException as exc:
                last_error = str(exc)
                LOGGER.warning("API request failed (%s); retrying", exc)
                self._sleep(attempt)
                continue

            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError as exc:
                    raise ApiError(
                        f"Invalid JSON from API: {response.text[:800]}"
                    ) from exc

            if response.status_code in {429, 500, 502, 503, 504}:
                last_error = self._response_error(response)
                LOGGER.warning(
                    "API returned %s; retrying (%s/%s)",
                    response.status_code,
                    attempt + 1,
                    self.settings.max_retries + 1,
                )
                self._sleep(attempt, response)
                continue

            raise ApiError(self._response_error(response))

        raise ApiError(f"API request failed after retries: {last_error}")

    def _sleep(self, attempt: int, response: requests.Response | None = None) -> None:
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    time.sleep(min(float(retry_after), 60.0))
                    return
                except ValueError:
                    pass
        time.sleep(min(2**attempt, 30))

    @staticmethod
    def _response_error(response: requests.Response) -> str:
        body = response.text.strip()
        if len(body) > 1200:
            body = body[:1200] + "..."
        return f"API returned HTTP {response.status_code}: {body}"
