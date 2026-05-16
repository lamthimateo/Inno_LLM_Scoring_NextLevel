"""LLM provider adapters.

Each adapter implements :class:`~src.adapters.base.ModelAdapter` and returns
a :class:`~src.adapters.base.ModelResult`. Supported native SDK paths:
``openai``, ``openrouter`` (OpenAI-compatible), ``anthropic``, ``google``
(Gemini via ``google-genai``), ``groq`` (OpenAI-compatible), ``mistral``,
and optional ``mistral-agent`` (Mistral Agents beta).
"""
