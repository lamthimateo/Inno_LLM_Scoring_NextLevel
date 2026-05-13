"""OpenRouter adapter (Chat Completions API).

OpenRouter exposes an OpenAI-compatible endpoint that proxies to dozens of
upstream providers (OpenAI, Anthropic, Google, Meta, Mistral, …) under a
single API key. This lets the benchmark hit four different models from
four different vendors without juggling four separate SDKs.

Reads ``OPENROUTER_API_KEY`` (preferred) or falls back to
``OPENAI_API_KEY`` (so a single key can route both endpoints during local
development).

The model ID is expected in OpenRouter's ``provider/model`` form, e.g.::

    openai/gpt-4o-mini
    anthropic/claude-3.5-haiku
    google/gemini-flash-1.5
    meta-llama/llama-3.1-70b-instruct
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

from .base import ModelAdapter, ModelResult
from .openai_adapter import _supports_temperature


def _is_retryable_exception(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    msg = str(exc).lower()
    if "ratelimit" in name or "rate limit" in msg or "429" in msg:
        return True
    if "timeout" in name or "timed out" in msg:
        return True
    if "apiconnection" in name or "connection" in name or "connection" in msg:
        return True
    if "server error" in msg or any(s in msg for s in ("500", "502", "503", "504")):
        return True
    return False


def _sleep_backoff_s(attempt: int) -> float:
    return min(8.0, 0.5 * (2 ** max(0, attempt - 1)))


class OpenRouterAdapter(ModelAdapter):
    BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(self, model: str):
        self.model = model
        self.api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
        self._referer = os.getenv("OPENROUTER_HTTP_REFERER", "https://github.com/inno-llm-scoring")
        self._app_title = os.getenv("OPENROUTER_APP_TITLE", "LLM Arena")

    def id(self) -> str:
        return f"openrouter:{self.model}"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def run(
        self,
        prompt: str,
        *,
        temperature: Optional[float] = 0.0,
        max_output_tokens: Optional[int] = 2048,
        timeout_s: Optional[float] = 120.0,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> ModelResult:
        if not self.api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. Export it or add it to .env."
            )

        try:
            from openai import OpenAI
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "Missing dependency. Install: pip install -r requirements.txt"
            ) from e

        client = OpenAI(
            api_key=self.api_key,
            base_url=self.BASE_URL,
            timeout=timeout_s,
            default_headers={
                "HTTP-Referer": self._referer,
                "X-Title": self._app_title,
            },
        )

        messages = [{"role": "user", "content": prompt}]
        last_exc: Optional[Exception] = None
        resp: Any = None
        t0 = time.time()

        # OpenRouter routes ``openai/o4-mini`` etc. to OpenAI, which rejects
        # ``temperature`` for reasoning models. Mirror the OpenAI adapter guard.
        allow_sampling = _supports_temperature(self.model)
        create_kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if max_output_tokens is not None:
            create_kwargs["max_tokens"] = max_output_tokens
        if allow_sampling and temperature is not None:
            create_kwargs["temperature"] = temperature
        extra = dict(kwargs)
        if not allow_sampling:
            extra.pop("temperature", None)
            extra.pop("top_p", None)
        create_kwargs.update(extra)

        for attempt in range(1, max_retries + 1):
            try:
                resp = client.chat.completions.create(**create_kwargs)
                last_exc = None
                break
            except Exception as e:
                last_exc = e
                if attempt >= max_retries or not _is_retryable_exception(e):
                    break
                time.sleep(_sleep_backoff_s(attempt))

        elapsed_ms = int((time.time() - t0) * 1000)
        if last_exc is not None:
            msg = str(last_exc).strip()
            raise RuntimeError(
                f"OpenRouter request failed for model '{self.model}' "
                f"after {max_retries} attempt(s): {msg}"
            ) from last_exc

        choice = (resp.choices[0] if getattr(resp, "choices", None) else None)
        raw_text = ""
        if choice is not None:
            msg = getattr(choice, "message", None)
            if msg is not None:
                raw_text = getattr(msg, "content", "") or ""

        usage = getattr(resp, "usage", None)
        meta: Dict[str, Any] = {
            "provider": "openrouter",
            "model": self.model,
            "response_id": getattr(resp, "id", None),
            "elapsed_ms": elapsed_ms,
            "retries": max_retries,
        }
        if usage is not None:
            meta["usage"] = (
                usage if isinstance(usage, dict) else getattr(usage, "__dict__", str(usage))
            )

        return ModelResult(model_id=self.id(), raw_text=raw_text, meta=meta)
