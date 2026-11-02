"""Groq adapter — OpenAI-compatible Chat Completions API.

Uses the official ``openai`` SDK against Groq's base URL (shared logic lives
in :class:`~src.adapters._openai_compat.OpenAICompatAdapter`). Reads
``GROQ_API_KEY`` from the environment.

See https://console.groq.com/docs/quickstart
"""

from __future__ import annotations

import os
from typing import Optional

from ._openai_compat import OpenAICompatAdapter


class GroqAdapter(OpenAICompatAdapter):
    provider = "groq"
    display_name = "Groq"
    BASE_URL = "https://api.groq.com/openai/v1"

    def resolve_api_key(self) -> Optional[str]:
        return os.getenv("GROQ_API_KEY")

    def missing_key_message(self) -> str:
        return "GROQ_API_KEY is not set. Export it or add it to .env."
