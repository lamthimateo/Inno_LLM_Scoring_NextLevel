"""Google (Gemini) adapter — stub.

Not wired to the real Google GenAI SDK yet. Kept here so the adapter surface is
visible and so the CLI can be extended later without restructuring.

To finish this adapter:
    1. Add `google-genai` to `requirements.txt` / `pyproject.toml`.
    2. Read `GOOGLE_API_KEY` from the environment in `__init__`.
    3. Implement `run()` mirroring `OpenAIAdapter.run()`:
         - call `client.models.generate_content(...)`
         - retry/backoff on transient errors
         - return `ModelResult(model_id=..., raw_text=..., meta={...})`
    4. Wire it into `src/runner/api_runner.py` (e.g. add `run_google_models`).
"""

from __future__ import annotations

import os

from .base import ModelAdapter, ModelResult


class GoogleAdapter(ModelAdapter):
    """Placeholder for the Google Gemini provider.

    `run()` raises `NotImplementedError` so callers fail fast and loudly
    rather than silently producing empty results.
    """

    def __init__(self, model: str):
        self.model = model
        self.api_key = os.getenv("GOOGLE_API_KEY")

    def id(self) -> str:
        return f"google:{self.model}"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def run(self, prompt: str, **kwargs) -> ModelResult:
        raise NotImplementedError(
            "GoogleAdapter is a stub. Wire the Google GenAI SDK here "
            "(env: GOOGLE_API_KEY). See module docstring for the steps."
        )
