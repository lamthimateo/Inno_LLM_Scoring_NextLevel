"""Anthropic (Claude) adapter — stub.

Not wired to the real Anthropic SDK yet. Kept here so the adapter surface is
visible and so the CLI can be extended later without restructuring.

To finish this adapter:
    1. Add `anthropic` to `requirements.txt` / `pyproject.toml`.
    2. Read `ANTHROPIC_API_KEY` from the environment in `__init__`.
    3. Implement `run()` mirroring `OpenAIAdapter.run()`:
         - call `client.messages.create(...)`
         - retry/backoff on transient errors
         - return `ModelResult(model_id=..., raw_text=..., meta={...})`
    4. Wire it into `src/runner/api_runner.py` (e.g. add `run_anthropic_models`).
"""

from __future__ import annotations

import os

from .base import ModelAdapter, ModelResult


class AnthropicAdapter(ModelAdapter):
    """Placeholder for the Anthropic provider.

    `run()` raises `NotImplementedError` so callers fail fast and loudly
    rather than silently producing empty results.
    """

    def __init__(self, model: str):
        self.model = model
        self.api_key = os.getenv("ANTHROPIC_API_KEY")

    def id(self) -> str:
        return f"anthropic:{self.model}"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def run(self, prompt: str, **kwargs) -> ModelResult:
        raise NotImplementedError(
            "AnthropicAdapter is a stub. Wire the Anthropic SDK here "
            "(env: ANTHROPIC_API_KEY). See module docstring for the steps."
        )
