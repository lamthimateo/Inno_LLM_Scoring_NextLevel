"""Shared base for providers that speak the OpenAI Chat Completions protocol.

Groq, OpenRouter and Ollama all expose ``/chat/completions`` and are called
through the official ``openai`` SDK with a different base URL, key and
(sometimes) headers. This class owns everything they have in common:

- building the request (same prompt shape, token limit and temperature for
  every provider, so results stay comparable),
- omitting sampling parameters for reasoning models that reject them,
- retry with backoff on transient errors,
- extracting the reply text and provider metadata into a
  :class:`~src.adapters.base.ModelResult`.

A concrete adapter only declares what differs: the provider prefix, the base
URL, how to find its API key, and optionally extra client kwargs, a custom
retry rule, failure wording or extra metadata.

The OpenAI *Responses* API adapter (:mod:`src.adapters.openai_adapter`) is a
different protocol and does not use this base.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from ._retry import is_retryable_exception, sleep_backoff_s
from .base import ModelAdapter, ModelResult
from .openai_adapter import _supports_temperature


class OpenAICompatAdapter(ModelAdapter):
    #: provider prefix of the model id (``groq`` -> ``groq:<model>``)
    provider: str = ""
    #: human-readable provider name used in error messages
    display_name: str = ""
    #: default endpoint; override :meth:`get_base_url` for a dynamic one
    BASE_URL: str = ""
    default_timeout_s: float = 120.0
    default_max_retries: int = 3
    #: exception type raised when every attempt failed
    error_class: type[RuntimeError] = RuntimeError

    def __init__(self, model: str):
        self.model = model
        self.api_key = self.resolve_api_key()

    # ------------------------------------------------------------------ hooks

    def resolve_api_key(self) -> Optional[str]:
        raise NotImplementedError

    def missing_key_message(self) -> str:
        raise NotImplementedError

    def get_base_url(self) -> str:
        return self.BASE_URL

    def client_kwargs(self) -> Dict[str, Any]:
        """Extra keyword arguments for ``OpenAI(...)`` (e.g. ``default_headers``)."""

        return {}

    def is_retryable(self, exc: Exception) -> bool:
        return is_retryable_exception(exc)

    def describe_failure(self, exc: Exception, attempts: int, timeout_s: float) -> str:
        msg = str(exc).strip()
        return (
            f"{self.display_name} request failed for model '{self.model}' "
            f"after {attempts} attempt(s): {msg}"
        )

    def extra_meta(self, resp: Any, raw_text: str, prompt: str) -> Dict[str, Any]:
        """Provider-specific metadata merged into ``ModelResult.meta``."""

        return {}

    # -------------------------------------------------------------- interface

    def id(self) -> str:
        return f"{self.provider}:{self.model}"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def run(
        self,
        prompt: str,
        *,
        temperature: Optional[float] = 0.0,
        max_output_tokens: Optional[int] = 2048,
        timeout_s: Optional[float] = None,
        max_retries: Optional[int] = None,
        **kwargs: Any,
    ) -> ModelResult:
        if not self.api_key:
            raise RuntimeError(self.missing_key_message())

        try:
            from openai import OpenAI
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "Missing dependency. Install: pip install -r requirements.txt"
            ) from e

        timeout = self.default_timeout_s if timeout_s is None else timeout_s
        attempts_allowed = self.default_max_retries if max_retries is None else max_retries

        client = OpenAI(
            api_key=self.api_key,
            base_url=self.get_base_url(),
            timeout=timeout,
            **self.client_kwargs(),
        )

        # Reasoning models (o1, o3, o4-mini, ...) reject temperature / top_p.
        allow_sampling = _supports_temperature(self.model)
        create_kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
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
        for attempt in range(1, attempts_allowed + 1):
            try:
                resp = client.chat.completions.create(**create_kwargs)
                last_exc = None
                break
            except Exception as e:
                last_exc = e
                if attempt >= attempts_allowed or not self.is_retryable(e):
                    break
                time.sleep(sleep_backoff_s(attempt))

        elapsed_ms = int((time.time() - t0) * 1000)
        if last_exc is not None:
            raise self.error_class(
                self.describe_failure(last_exc, attempts_allowed, timeout)
            ) from last_exc

        choice = resp.choices[0] if getattr(resp, "choices", None) else None
        raw_text = ""
        if choice is not None:
            message = getattr(choice, "message", None)
            if message is not None:
                raw_text = getattr(message, "content", "") or ""

        usage = getattr(resp, "usage", None)
        meta: Dict[str, Any] = {
            "provider": self.provider,
            "model": self.model,
            "response_id": getattr(resp, "id", None),
            "elapsed_ms": elapsed_ms,
            "retries": attempts_allowed,
        }
        if usage is not None:
            meta["usage"] = (
                usage if isinstance(usage, dict) else getattr(usage, "__dict__", str(usage))
            )
        meta.update(self.extra_meta(resp, raw_text, prompt))

        return ModelResult(model_id=self.id(), raw_text=raw_text, meta=meta)
