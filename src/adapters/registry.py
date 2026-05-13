"""Adapter registry — resolve a model ID string into a runnable adapter.

Model IDs use a ``provider:model`` form, e.g.::

    openai:gpt-4o-mini
    openrouter:openai/gpt-4o-mini
    openrouter:anthropic/claude-3.5-haiku

The web UI offers a small curated list (the ``DEFAULT_MODELS`` below) but
nothing prevents an admin from typing any other valid model string.
"""

from __future__ import annotations

from typing import List

from src.adapters.base import ModelAdapter
from src.adapters.openai_adapter import OpenAIAdapter
from src.adapters.openrouter_adapter import OpenRouterAdapter


DEFAULT_MODELS: List[str] = [
    "openrouter:openai/gpt-4o-mini",
    "openrouter:anthropic/claude-3.5-haiku",
    "openrouter:google/gemini-flash-1.5",
    "openrouter:meta-llama/llama-3.1-70b-instruct",
]


def get_adapter(model_id: str) -> ModelAdapter:
    """Resolve ``provider:model`` into a configured :class:`ModelAdapter`."""

    if ":" not in model_id:
        raise ValueError(
            f"Invalid model id {model_id!r}. Expected 'provider:model' "
            f"(e.g. 'openrouter:openai/gpt-4o-mini')."
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
