"""Adapter interface shared by every provider.

A :class:`ModelAdapter` knows how to talk to one provider/model. It returns
a :class:`ModelResult` which the rest of the pipeline treats as opaque:

- ``model_id``   — stable string identifier (e.g. ``openai:gpt-4.1``)
- ``raw_text``   — the model's reply, unmodified, ready for the MCQ parser
- ``meta``       — provider metadata (usage, latency, response id, errors)
                   that gets JSON-encoded into ``model_runs.meta_json``.
"""

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
