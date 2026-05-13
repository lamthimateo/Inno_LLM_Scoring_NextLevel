"""Adapter registry — resolve a model ID string into a runnable adapter.

Model IDs use a ``provider:model`` form, e.g.::

    openai:gpt-5.5
    openrouter:openai/gpt-5.5
    openrouter:anthropic/claude-sonnet-4

The web UI offers a small curated list (the ``DEFAULT_MODELS`` below) but
nothing prevents an admin from typing any other valid model string.

Picking the preset:

- If ``OPENROUTER_API_KEY`` is set we route through OpenRouter so we can
  compare across providers (OpenAI / Anthropic / Google / DeepSeek) with a
  single key. OpenRouter mirrors the OpenAI Chat Completions API, so we
  reuse the OpenAI Python SDK with a custom ``base_url``.
- If only ``OPENAI_API_KEY`` is set we fall back to four OpenAI variants
  hitting the Responses API directly. This is what the local ``.env``
  ships with today (no OpenRouter key configured) so we default to it.

Model ids in the preset are 2026 OpenAI ids verified against the public
docs at ``https://developers.openai.com/api/docs/models/``.
"""

from __future__ import annotations

import os
from typing import List

from src.adapters.base import ModelAdapter
from src.adapters.openai_adapter import OpenAIAdapter
from src.adapters.openrouter_adapter import OpenRouterAdapter


OPENROUTER_PRESET: List[str] = [
    "openrouter:openai/gpt-5.5",
    "openrouter:anthropic/claude-sonnet-4.5",
    "openrouter:google/gemini-2.5-pro",
    "openrouter:deepseek/deepseek-v3.2",
]

OPENAI_PRESET: List[str] = [
    "openai:gpt-5.5",
    "openai:gpt-5.4-mini",
    "openai:gpt-5-mini",
    "openai:o4-mini",
]


def _pick_default_models() -> List[str]:
    """Pick the preset that matches the configured provider key.

    Resolved at import time. Restart the app after rotating keys.
    """

    if os.getenv("OPENROUTER_API_KEY"):
        return list(OPENROUTER_PRESET)
    return list(OPENAI_PRESET)


DEFAULT_MODELS: List[str] = _pick_default_models()


def get_adapter(model_id: str) -> ModelAdapter:
    """Resolve ``provider:model`` into a configured :class:`ModelAdapter`."""

    if ":" not in model_id:
        raise ValueError(
            f"Invalid model id {model_id!r}. Expected 'provider:model' "
            f"(e.g. 'openai:gpt-5.5' or 'openrouter:openai/gpt-5.5')."
        )
    provider, _, model = model_id.partition(":")
    provider = provider.lower().strip()
    model = model.strip()
    if not model:
        raise ValueError(f"Empty model in {model_id!r}")

    if provider == "openai":
        return OpenAIAdapter(model)
    if provider == "openrouter":
        return OpenRouterAdapter(model)
    raise ValueError(
        f"Unknown provider {provider!r}. Supported: openai, openrouter."
    )
