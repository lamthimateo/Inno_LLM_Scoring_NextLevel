import os
import time
from typing import Any, Dict, Optional

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
        **kwargs: Any,
    ) -> ModelResult:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not set.")

        try:
            from openai import OpenAI
        except Exception as e:  # pragma: no cover
            raise RuntimeError("Missing dependency. Install: pip install -r requirements.txt") from e

        client = OpenAI(api_key=self.api_key, timeout=timeout_s)
        t0 = time.time()
        resp = client.responses.create(
            model=self.model,
            input=prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            **kwargs,
        )
        elapsed_ms = int((time.time() - t0) * 1000)

        raw_text = _extract_output_text(resp)
        usage = getattr(resp, "usage", None)

        meta: Dict[str, Any] = {
            "provider": "openai",
            "model": self.model,
            "response_id": getattr(resp, "id", None),
            "elapsed_ms": elapsed_ms,
        }
        if usage is not None:
            # Keep as plain dict if possible (Row/JSON safe)
            meta["usage"] = usage if isinstance(usage, dict) else getattr(usage, "__dict__", str(usage))

        return ModelResult(model_id=self.id(), raw_text=raw_text, meta=meta)