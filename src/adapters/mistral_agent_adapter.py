"""Mistral Agents (beta) — ``beta.conversations.start``.

Uses the same ``MISTRAL_API_KEY`` as :class:`~src.adapters.mistral_adapter.MistralAdapter`,
but talks to a configured **Agent** instead of a raw chat model.

Model IDs look like ``mistral-agent:<agent_id>`` (the segment after the first ``:``
is passed as ``agent_id``). Optional ``MISTRAL_AGENT_VERSION`` (default ``0``) is
sent as ``agent_version``.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

from ._retry import is_retryable_exception, sleep_backoff_s
from .base import ModelAdapter, ModelResult


def _outputs_assistant_text(outputs: List[Any]) -> str:
    """Collect assistant ``message.output`` text from a conversation response."""

    parts: list[str] = []
    for out in outputs:
        if getattr(out, "type", None) != "message.output":
            continue
        content = getattr(out, "content", None)
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for chunk in content:
                txt = getattr(chunk, "text", None)
                if txt:
                    parts.append(txt)
    return "\n".join(parts)


class MistralAgentAdapter(ModelAdapter):
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.api_key = os.getenv("MISTRAL_API_KEY")

    def id(self) -> str:
        return f"mistral-agent:{self.agent_id}"

    def is_configured(self) -> bool:
        return bool(self.api_key and self.agent_id)

    def run(
        self,
        prompt: str,
        *,
        timeout_ms: Optional[int] = 600_000,
        max_retries: int = 3,
    ) -> ModelResult:
        if not self.api_key:
            raise RuntimeError(
                "MISTRAL_API_KEY is not set. Export it or add it to .env."
            )
        if not self.agent_id:
            raise RuntimeError("Empty Mistral agent id in model string.")

        try:
            from mistralai import Mistral
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "Missing dependency. Install: pip install mistralai"
            ) from e

        ver_raw = os.getenv("MISTRAL_AGENT_VERSION", "0")
        try:
            agent_version: int | str = int(ver_raw)
        except ValueError:
            agent_version = ver_raw

        client = Mistral(api_key=self.api_key, timeout_ms=timeout_ms)
        inputs = [{"role": "user", "content": prompt}]

        last_exc: Optional[Exception] = None
        resp: Any = None
        t0 = time.time()
        for attempt in range(1, max_retries + 1):
            try:
                resp = client.beta.conversations.start(
                    agent_id=self.agent_id,
                    agent_version=agent_version,
                    inputs=inputs,
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
            raise RuntimeError(
                f"Mistral Agent request failed for agent '{self.agent_id}' "
                f"after {max_retries} attempt(s): {msg}"
            ) from last_exc

        outputs = getattr(resp, "outputs", None) or []
        raw_text = _outputs_assistant_text(outputs)
        usage = getattr(resp, "usage", None)
        meta: Dict[str, Any] = {
            "provider": "mistral-agent",
            "agent_id": self.agent_id,
            "conversation_id": getattr(resp, "conversation_id", None),
            "elapsed_ms": elapsed_ms,
            "retries": max_retries,
        }
        if usage is not None:
            meta["usage"] = (
                usage if isinstance(usage, dict) else getattr(usage, "__dict__", str(usage))
            )

        return ModelResult(model_id=self.id(), raw_text=raw_text, meta=meta)
