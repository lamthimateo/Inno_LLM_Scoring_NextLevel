"""Google/Gemini adapter stub."""

from .base import ModelAdapter, ModelResult


class GoogleAdapter(ModelAdapter):
    def __init__(self, model: str):
        self.model = model

    def id(self) -> str:
        return f"google:{self.model}"

    def run(self, prompt: str, **kwargs) -> ModelResult:
        raise NotImplementedError("Wire the Gemini SDK/API here (env: GOOGLE_API_KEY).")
