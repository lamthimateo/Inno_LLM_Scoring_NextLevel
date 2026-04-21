import os
import time
from typing import Any, Dict, Optional, Tuple

from .base import ModelAdapter, ModelResult


def _extract_output_text(resp: Any) -> str:
    """
    Best-effort extraction for the official OpenAI Python SDK (Responses API).
    Keeps the rest of the pipeline independent from SDK response shape tweaks.
    """
    t = getattr(resp, "output_text", None)
    if isinstance(t, str) and t.strip() != "":
        return t

    output = getattr(resp, "output", None)
    if isinstance(output, list):
        parts = []
        for item in output:
            content = getattr(item, "content", None)
            if not isinstance(content, list):
                continue
            for c in content:
                if getattr(c, "type", None) in ("output_text", "text") and getattr(c, "text", None):
                    parts.append(getattr(c, "text"))
        if parts:
            return "\n".join(parts)

    return str(resp)


def _is_retryable_exception(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    msg = str(exc).lower()
    if "ratelimit" in name or "rate limit" in msg or "429" in msg:
        return True
    if "timeout" in name or "timed out" in msg:
        return True
    if "apiconnection" in name or "connection" in name or "connection" in msg:
        return True
    if "server error" in msg or "5xx" in msg or "503" in msg or "502" in msg or "500" in msg:
        return True
    return False


def _sleep_backoff_s(attempt: int) -> float:
    # 0.5, 1, 2, 4 ... capped
    return min(8.0, 0.5 * (2 ** max(0, attempt - 1)))


class OpenAIAdapter(ModelAdapter):
    def __init__(self, model: str):
        self.model = model
        self.api_key = os.getenv("OPENAI_API_KEY")

    def id(self) -> str:
        return f"openai:{self.model}"

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
            raise RuntimeError("OPENAI_API_KEY is not set. Export it or put it in your environment.")

        try:
            from openai import OpenAI
        except Exception as e:  # pragma: no cover
            raise RuntimeError("Missing dependency. Install: pip install -r requirements.txt") from e

        client = OpenAI(api_key=self.api_key, timeout=timeout_s)
        last_exc: Optional[Exception] = None
        resp: Any = None
        t0 = time.time()
        for attempt in range(1, max_retries + 1):
            try:
                resp = client.responses.create(
                    model=self.model,
                    input=prompt,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    **kwargs,
                )
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
            raise RuntimeError(f"OpenAI request failed for model '{self.model}' after {max_retries} attempt(s): {msg}") from last_exc

        raw_text = _extract_output_text(resp)
        usage = getattr(resp, "usage", None)

        meta: Dict[str, Any] = {
            "provider": "openai",
            "model": self.model,
            "response_id": getattr(resp, "id", None),
            "elapsed_ms": elapsed_ms,
            "retries": max_retries,
        }
        if usage is not None:
            # Keep as plain dict if possible (Row/JSON safe)
            meta["usage"] = usage if isinstance(usage, dict) else getattr(usage, "__dict__", str(usage))

        return ModelResult(model_id=self.id(), raw_text=raw_text, meta=meta)