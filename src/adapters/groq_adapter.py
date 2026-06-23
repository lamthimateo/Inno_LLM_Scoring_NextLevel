"""Groq adapter — OpenAI-compatible Chat Completions API.

Uses the official ``openai`` SDK against Groq's base URL. Reads
``GROQ_API_KEY`` from the environment.

See https://console.groq.com/docs/quickstart
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

from ._retry import is_retryable_exception, sleep_backoff_s
from .base import ModelAdapter, ModelResult
from .openai_adapter import _supports_temperature


class GroqAdapter(ModelAdapter):
    BASE_URL = "https://api.groq.com/openai/v1"

    def __init__(self, model: str):
        self.model = model
        self.api_key = os.getenv("GROQ_API_KEY")

    def id(self) -> str:
        return f"groq:{self.model}"

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
                "GROQ_API_KEY is not set. Export it or add it to .env."
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
        )
        messages = [{"role": "user", "content": prompt}]
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

        last_exc: Optional[Exception] = None
        resp: Any = None
        t0 = time.time()
        for attempt in range(1, max_retries + 1):
            try:
                resp = client.chat.completions.create(**create_kwargs)
                last_exc = None
                break
            except Exception as e:
                last_exc = e
                if attempt >= max_retries or not is_retryable_exception(e):
                    break
                time.sleep(sleep_backoff_s(attempt))

        elapsed_ms = int((time.time() - t0) * 1000)
        if last_exc is not None:
            msg = str(last_exc).strip()
            raise RuntimeError(
                f"Groq request failed for model '{self.model}' "
                f"after {max_retries} attempt(s): {msg}"
            ) from last_exc

        choice = resp.choices[0] if getattr(resp, "choices", None) else None
        raw_text = ""
        if choice is not None:
            msg = getattr(choice, "message", None)
            if msg is not None:
                raw_text = getattr(msg, "content", "") or ""

        usage = getattr(resp, "usage", None)
        meta: Dict[str, Any] = {
            "provider": "groq",
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
