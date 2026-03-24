"""OpenAI adapter stub.

This file is intentionally a **stub** to keep the repo dependency-light and future-proof.

Implementation plan:
- Read API key from env `OPENAI_API_KEY`
- Use the official OpenAI SDK or HTTPS calls
- Return raw model output text

Keep the signature stable so runner/evaluator code does not change.
"""

from .base import ModelAdapter, ModelResult


class OpenAIAdapter(ModelAdapter):
    def __init__(self, model: str):
        self.model = model

    def id(self) -> str:
        return f"openai:{self.model}"

    def run(self, prompt: str, **kwargs) -> ModelResult:
        raise NotImplementedError("Wire the OpenAI SDK/API here (env: OPENAI_API_KEY).")
