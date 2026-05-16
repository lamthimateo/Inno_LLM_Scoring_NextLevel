"""Anthropic (Claude) adapter — Messages API."""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

from ._retry import is_retryable_exception, sleep_backoff_s
from .base import ModelAdapter, ModelResult


def _message_text(message: Any) -> str:
    parts: list[str] = []
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", "") or "")
    return "".join(parts)


class AnthropicAdapter(ModelAdapter):
    def __init__(self, model: str):
        self.model = model
        self.api_key = os.getenv("ANTHROPIC_API_KEY")

    def id(self) -> str:
        return f"anthropic:{self.model}"

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
                "ANTHROPIC_API_KEY is not set. Export it or add it to .env."
            )

        try:
            import anthropic
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "Missing dependency. Install: pip install anthropic"
            ) from e

        client = anthropic.Anthropic(
            api_key=self.api_key,
            timeout=timeout_s,
            max_retries=0,
        )

        create_kwargs: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_output_tokens or 2048,
            "messages": [{"role": "user", "content": prompt}],
        }
        if temperature is not None:
            create_kwargs["temperature"] = temperature
        create_kwargs.update(kwargs)

        last_exc: Optional[Exception] = None
        message: Any = None
        t0 = time.time()
        for attempt in range(1, max_retries + 1):
            try:
                message = client.messages.create(**create_kwargs)
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
                f"Anthropic request failed for model '{self.model}' "
                f"after {max_retries} attempt(s): {msg}"
            ) from last_exc

        raw_text = _message_text(message)
        usage = getattr(message, "usage", None)
        meta: Dict[str, Any] = {
            "provider": "anthropic",
            "model": self.model,
            "response_id": getattr(message, "id", None),
            "elapsed_ms": elapsed_ms,
            "stop_reason": getattr(message, "stop_reason", None),
            "retries": max_retries,
        }
        if usage is not None:
            meta["usage"] = (
                usage if isinstance(usage, dict) else getattr(usage, "__dict__", str(usage))
            )

        return ModelResult(model_id=self.id(), raw_text=raw_text, meta=meta)
