"""Google Gemini adapter (Google AI Studio / Gemini API).

Uses the ``google-genai`` SDK. Reads ``GOOGLE_API_KEY`` or ``GEMINI_API_KEY``.

See https://ai.google.dev/gemini-api/docs/text-generation
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

from ._retry import is_retryable_exception, sleep_backoff_s
from .base import ModelAdapter, ModelResult


def google_api_credentials() -> Optional[str]:
    """Resolve the Gemini API key from the environment (trimmed)."""

    raw = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or ""
    return raw.strip() or None


class GoogleAdapter(ModelAdapter):
    def __init__(self, model: str):
        self.model = model
        self.api_key = google_api_credentials()

    def id(self) -> str:
        return f"google:{self.model}"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def run(
        self,
        prompt: str,
        *,
        temperature: Optional[float] = 0.0,
        max_output_tokens: Optional[int] = 2048,
        # Large MCQ batches can take minutes; ``HttpOptions.timeout`` is **milliseconds**.
        timeout_s: Optional[float] = 600.0,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> ModelResult:
        if not self.api_key:
            raise RuntimeError(
                "Gemini API key is not set. Set GOOGLE_API_KEY or GEMINI_API_KEY "
                "in .env (create one at https://aistudio.google.com/apikey)."
            )

        try:
            from google import genai
            from google.genai import types
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "Missing dependency. Install: pip install google-genai"
            ) from e

        ts = float(timeout_s if timeout_s is not None else 600.0)
        timeout_ms = max(1, int(ts * 1000))
        client = genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(timeout=timeout_ms),
        )

        config = types.GenerateContentConfig(
            temperature=temperature if temperature is not None else 0.0,
            max_output_tokens=max_output_tokens or 2048,
        )

        last_exc: Optional[Exception] = None
        response: Any = None
        t0 = time.time()
        for attempt in range(1, max_retries + 1):
            try:
                response = client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=config,
                )
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
            if "API_KEY_INVALID" in msg or "API key not valid" in msg:
                raise RuntimeError(
                    f"Google Gemini rejected the API key for model '{self.model}'. "
                    "Set a valid GOOGLE_API_KEY or GEMINI_API_KEY from "
                    "https://aistudio.google.com/apikey, then restart the app "
                    "(docker compose up -d --force-recreate if using Docker)."
                ) from last_exc
            raise RuntimeError(
                f"Google Gemini request failed for model '{self.model}' "
                f"after {max_retries} attempt(s): {msg}"
            ) from last_exc

        raw_text = getattr(response, "text", None) or ""
        usage = getattr(response, "usage_metadata", None) or getattr(response, "usage", None)
        meta: Dict[str, Any] = {
            "provider": "google",
            "model": self.model,
            "response_id": getattr(response, "response_id", None)
            or getattr(response, "id", None),
            "elapsed_ms": elapsed_ms,
            "retries": max_retries,
        }
        if usage is not None:
            md = getattr(usage, "model_dump", None)
            if callable(md):
                try:
                    meta["usage"] = md(mode="json")
                except TypeError:
                    meta["usage"] = md()
            elif isinstance(usage, dict):
                meta["usage"] = usage
            else:
                meta["usage"] = getattr(usage, "__dict__", str(usage))

        return ModelResult(model_id=self.id(), raw_text=raw_text, meta=meta)
