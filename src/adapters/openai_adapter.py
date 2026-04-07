"""OpenAI adapter (preparation version for Week 2).

Goal for this sprint:
- choose OpenAI as the first provider
- prepare the adapter structure cleanly
- define how API results will be returned to the pipeline

Full integration can be completed in the next sprint.
"""

import os
from .base import ModelAdapter, ModelResult


class OpenAIAdapter(ModelAdapter):
    def __init__(self, model: str):
        self.model = model
        self.api_key = os.getenv("OPENAI_API_KEY")

    def id(self) -> str:
        return f"openai:{self.model}"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def run(self, prompt: str, **kwargs) -> ModelResult:
        """
        Planned API flow:
        1. read OPENAI_API_KEY from env
        2. send prompt to OpenAI model
        3. extract plain text output
        4. return ModelResult for existing parser/scoring pipeline
        """
        if not self.api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Add it to your environment or .env file."
            )

        # Week 2 preparation only:
        # Full OpenAI API call will be implemented in the next sprint.
        raise NotImplementedError(
            "OpenAI adapter prepared. Real API call will be implemented next sprint."
        )