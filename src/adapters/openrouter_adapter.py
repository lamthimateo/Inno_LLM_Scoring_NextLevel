"""OpenRouter adapter (Chat Completions API).

OpenRouter exposes an OpenAI-compatible endpoint that proxies to dozens of
upstream providers (OpenAI, Anthropic, Google, Meta, Mistral, …) under a
single API key. This lets the benchmark hit four different models from
four different vendors without juggling four separate SDKs. The shared
request/retry logic lives in
:class:`~src.adapters._openai_compat.OpenAICompatAdapter`.

Reads ``OPENROUTER_API_KEY`` (preferred), ``OPENROUTER_API`` (alias), or
falls back to ``OPENAI_API_KEY`` (so a single key can route both endpoints
during local development).

The model ID is expected in OpenRouter's ``provider/model`` form, e.g.::

    openai/gpt-4o-mini
    anthropic/claude-3.5-haiku
    google/gemini-flash-1.5
    meta-llama/llama-3.1-70b-instruct
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from ._openai_compat import OpenAICompatAdapter


def openrouter_api_credentials() -> Optional[str]:
    """Resolve the OpenRouter-compatible API key from the environment."""

    return (
        os.getenv("OPENROUTER_API_KEY")
        or os.getenv("OPENROUTER_API")
        or os.getenv("OPENAI_API_KEY")
    )


def openrouter_explicit_credentials() -> Optional[str]:
    """Keys that activate the OpenRouter default preset (OpenAI key alone does not)."""

    return os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENROUTER_API")


class OpenRouterAdapter(OpenAICompatAdapter):
    provider = "openrouter"
    display_name = "OpenRouter"
    BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(self, model: str):
        self._referer = os.getenv("OPENROUTER_HTTP_REFERER", "https://github.com/inno-llm-scoring")
        self._app_title = os.getenv("OPENROUTER_APP_TITLE", "LLM Arena")
        super().__init__(model)

    def resolve_api_key(self) -> Optional[str]:
        return openrouter_api_credentials()

    def missing_key_message(self) -> str:
        return (
            "OpenRouter API key is not set. Set OPENROUTER_API_KEY or "
            "OPENROUTER_API (or OPENAI_API_KEY for dev) in the environment."
        )

    def client_kwargs(self) -> Dict[str, Any]:
        # Attribution headers OpenRouter uses for traffic routing.
        return {
            "default_headers": {
                "HTTP-Referer": self._referer,
                "X-Title": self._app_title,
            }
        }
