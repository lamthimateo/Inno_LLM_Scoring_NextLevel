"""Anthropic adapter stub (Claude/Sonnet)."""

from .base import ModelAdapter, ModelResult


class AnthropicAdapter(ModelAdapter):
    def __init__(self, model: str):
        self.model = model

    def id(self) -> str:
        return f"anthropic:{self.model}"

    def run(self, prompt: str, **kwargs) -> ModelResult:
        raise NotImplementedError("Wire the Anthropic SDK/API here (env: ANTHROPIC_API_KEY).")
