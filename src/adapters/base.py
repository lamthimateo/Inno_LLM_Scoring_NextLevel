from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass
class ModelResult:
    model_id: str
    raw_text: str
    meta: Dict[str, Any]


class ModelAdapter:
    """Interface for calling an LLM."""

    def id(self) -> str:
        raise NotImplementedError

    def run(self, prompt: str, **kwargs) -> ModelResult:
        raise NotImplementedError
