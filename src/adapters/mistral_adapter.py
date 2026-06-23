"""Mistral AI adapter (chat completions).

Reads ``MISTRAL_API_KEY`` from the environment.

See https://docs.mistral.ai/getting-started/clients/
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

from ._retry import is_retryable_exception, sleep_backoff_s
from .base import ModelAdapter, ModelResult


class MistralAdapter(ModelAdapter):
    def __init__(self, model: str):
        self.model = model
        self.api_key = os.getenv("MISTRAL_API_KEY")

    def id(self) -> str:
        return f"mistral:{self.model}"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def run(
        self,
        prompt: str,
        *,
        temperature: Optional[float] = 0.0,
        max_output_tokens: Optional[int] = 2048,
        timeout_ms: Optional[int] = 120_000,
        max_retries: int = 3,
    ) -> ModelResult:
        if not self.api_key:
            raise RuntimeError(
                "MISTRAL_API_KEY is not set. Export it or add it to .env."
            )

        try:
            from mistralai import Mistral
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "Missing dependency. Install: pip install mistralai"
            ) from e

        client = Mistral(api_key=self.api_key, timeout_ms=timeout_ms)
        last_exc: Optional[Exception] = None
        resp: Any = None
        t0 = time.time()

        create_kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if temperature is not None:
            create_kwargs["temperature"] = temperature
        if max_output_tokens is not None:
            create_kwargs["max_tokens"] = max_output_tokens

        for attempt in range(1, max_retries + 1):
            try:
                resp = client.chat.complete(**create_kwargs)
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
                f"Mistral request failed for model '{self.model}' "
                f"after {max_retries} attempt(s): {msg}"
            ) from last_exc

        raw_text = ""
        choices = getattr(resp, "choices", None)
        if choices:
            ch0 = choices[0]
            msg = getattr(ch0, "message", None)
            if msg is not None:
                raw_text = getattr(msg, "content", "") or ""

        usage = getattr(resp, "usage", None)
        meta: Dict[str, Any] = {
            "provider": "mistral",
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
