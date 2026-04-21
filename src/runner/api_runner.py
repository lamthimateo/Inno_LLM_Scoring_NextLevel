from typing import Iterable, List, Optional

from src.adapters.openai_adapter import OpenAIAdapter
from src.adapters.base import ModelResult


def run_openai_models(
    prompt: str,
    models: Iterable[str],
    *,
    temperature: float = 0.0,
    max_output_tokens: int = 2048,
    timeout_s: float = 120.0,
    max_retries: int = 3,
) -> List[ModelResult]:
    results: List[ModelResult] = []
    for m in models:
        adapter = OpenAIAdapter(model=m)
        results.append(
            adapter.run(
                prompt,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                timeout_s=timeout_s,
                max_retries=max_retries,
            )
        )
    return results
