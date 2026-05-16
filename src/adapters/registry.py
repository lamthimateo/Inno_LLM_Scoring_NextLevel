"""Adapter registry — resolve a model ID string into a runnable adapter.

Model IDs use a ``provider:model`` form, e.g.::

    openai:gpt-5.5
    openrouter:openai/gpt-5.5
    anthropic:claude-sonnet-4-20250514
    google:gemini-2.5-flash
    groq:llama-3.3-70b-versatile
    mistral:mistral-large-latest
    mistral-agent:<agent_id> (catalog entry appears when ``MISTRAL_AGENT_ID`` is set)

The web UI offers a curated list (:data:`MODEL_CATALOG`). Default selection:

- If **all four** native keys are set — ``ANTHROPIC_API_KEY``,
  ``GOOGLE_API_KEY``, ``GROQ_API_KEY``, ``MISTRAL_API_KEY`` — the default
  preset is one model from each native adapter (four-way comparison without
  OpenRouter).
- Else if ``OPENROUTER_API_KEY`` or ``OPENROUTER_API`` is set, the four OpenRouter catalog entries
  are the default (cross-provider via one key).
- Else the four OpenAI-direct entries are the default.

Restart the app after rotating provider keys — the catalog resolves defaults
at import time.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List

from src.adapters.base import ModelAdapter
from src.adapters.anthropic_adapter import AnthropicAdapter
from src.adapters.google_adapter import GoogleAdapter, google_api_credentials
from src.adapters.groq_adapter import GroqAdapter
from src.adapters.mistral_adapter import MistralAdapter
from src.adapters.mistral_agent_adapter import MistralAgentAdapter
from src.adapters.openai_adapter import OpenAIAdapter
from src.adapters.openrouter_adapter import (
    OpenRouterAdapter,
    openrouter_api_credentials,
    openrouter_explicit_credentials,
)


GROUP_OPENAI_DIRECT = "OpenAI direct"
GROUP_OPENROUTER = "OpenRouter cross-provider"
GROUP_ANTHROPIC = "Anthropic direct"
GROUP_GOOGLE = "Google Gemini"
GROUP_GROQ = "Groq"
GROUP_MISTRAL = "Mistral AI"

NATIVE_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
)


@dataclass(frozen=True)
class CatalogEntry:
    """One picker option in the curated model catalog."""

    id: str
    label: str
    provider: str
    group: str
    requires_env: str
    is_default: bool


def _native_quorum() -> bool:
    return all(os.getenv(k) for k in NATIVE_ENV_KEYS)


def _build_catalog() -> List[CatalogEntry]:
    native_default = _native_quorum()
    openrouter_default = bool(openrouter_explicit_credentials()) and not native_default
    openai_default = not native_default and not openrouter_default

    native_models: List[CatalogEntry] = [
        CatalogEntry(
            id="anthropic:claude-sonnet-4-20250514",
            label="Claude Sonnet 4",
            provider="anthropic",
            group=GROUP_ANTHROPIC,
            requires_env="ANTHROPIC_API_KEY",
            is_default=native_default,
        ),
        CatalogEntry(
            id="google:gemini-2.5-flash",
            label="Gemini 2.5 Flash",
            provider="google",
            group=GROUP_GOOGLE,
            requires_env="GOOGLE_API_KEY",
            is_default=native_default,
        ),
        CatalogEntry(
            id="groq:llama-3.3-70b-versatile",
            label="Llama 3.3 70B (Groq)",
            provider="groq",
            group=GROUP_GROQ,
            requires_env="GROQ_API_KEY",
            is_default=native_default,
        ),
        CatalogEntry(
            id="mistral:mistral-large-latest",
            label="Mistral Large (latest)",
            provider="mistral",
            group=GROUP_MISTRAL,
            requires_env="MISTRAL_API_KEY",
            is_default=native_default,
        ),
    ]

    _mistral_agent_id = os.getenv("MISTRAL_AGENT_ID", "").strip()
    if _mistral_agent_id:
        native_models.append(
            CatalogEntry(
                id=f"mistral-agent:{_mistral_agent_id}",
                label="Mistral Agent (beta)",
                provider="mistral-agent",
                group=GROUP_MISTRAL,
                requires_env="MISTRAL_API_KEY",
                is_default=False,
            )
        )

    openai_entries = [
        CatalogEntry(
            id="openai:gpt-5.5",
            label="GPT-5.5",
            provider="openai",
            group=GROUP_OPENAI_DIRECT,
            requires_env="OPENAI_API_KEY",
            is_default=openai_default,
        ),
        CatalogEntry(
            id="openai:gpt-5.4-mini",
            label="GPT-5.4 mini",
            provider="openai",
            group=GROUP_OPENAI_DIRECT,
            requires_env="OPENAI_API_KEY",
            is_default=openai_default,
        ),
        CatalogEntry(
            id="openai:gpt-5-mini",
            label="GPT-5 mini",
            provider="openai",
            group=GROUP_OPENAI_DIRECT,
            requires_env="OPENAI_API_KEY",
            is_default=openai_default,
        ),
        CatalogEntry(
            id="openai:o4-mini",
            label="o4 mini",
            provider="openai",
            group=GROUP_OPENAI_DIRECT,
            requires_env="OPENAI_API_KEY",
            is_default=openai_default,
        ),
    ]

    openrouter_entries = [
        CatalogEntry(
            id="openrouter:openai/gpt-5.5",
            label="GPT-5.5 (via OpenRouter)",
            provider="openrouter",
            group=GROUP_OPENROUTER,
            requires_env="OPENROUTER_API_KEY",
            is_default=openrouter_default,
        ),
        CatalogEntry(
            id="openrouter:anthropic/claude-sonnet-4.5",
            label="Claude Sonnet 4.5",
            provider="openrouter",
            group=GROUP_OPENROUTER,
            requires_env="OPENROUTER_API_KEY",
            is_default=openrouter_default,
        ),
        CatalogEntry(
            id="openrouter:google/gemini-2.5-pro",
            label="Gemini 2.5 Pro",
            provider="openrouter",
            group=GROUP_OPENROUTER,
            requires_env="OPENROUTER_API_KEY",
            is_default=openrouter_default,
        ),
        CatalogEntry(
            id="openrouter:deepseek/deepseek-v3.2",
            label="DeepSeek V3.2",
            provider="openrouter",
            group=GROUP_OPENROUTER,
            requires_env="OPENROUTER_API_KEY",
            is_default=openrouter_default,
        ),
    ]

    return openai_entries + openrouter_entries + native_models


MODEL_CATALOG: List[CatalogEntry] = _build_catalog()


def catalog_by_id() -> Dict[str, CatalogEntry]:
    return {e.id: e for e in MODEL_CATALOG}


def catalog_entry_env_ok(entry: CatalogEntry) -> bool:
    """Whether ``entry`` can run given current environment variables."""

    if entry.requires_env == "OPENROUTER_API_KEY":
        return bool(openrouter_explicit_credentials())
    if entry.requires_env == "GOOGLE_API_KEY":
        return bool(google_api_credentials())
    return bool(os.getenv(entry.requires_env))


def catalog_grouped() -> List[tuple[str, List[CatalogEntry]]]:
    groups: dict[str, list[CatalogEntry]] = {}
    for entry in MODEL_CATALOG:
        groups.setdefault(entry.group, []).append(entry)
    return list(groups.items())


def group_is_available(group: str) -> bool:
    entries = [e for e in MODEL_CATALOG if e.group == group]
    if not entries:
        return False
    return all(catalog_entry_env_ok(e) for e in entries)


def default_catalog_ids() -> List[str]:
    return [e.id for e in MODEL_CATALOG if e.is_default]


OPENROUTER_PRESET: List[str] = [
    e.id for e in MODEL_CATALOG if e.group == GROUP_OPENROUTER
]
OPENAI_PRESET: List[str] = [
    e.id for e in MODEL_CATALOG if e.group == GROUP_OPENAI_DIRECT
]
DEFAULT_MODELS: List[str] = default_catalog_ids()


def get_adapter(model_id: str) -> ModelAdapter:
    if ":" not in model_id:
        raise ValueError(
            f"Invalid model id {model_id!r}. Expected 'provider:model' "
            f"(e.g. 'openai:gpt-5.5' or 'groq:llama-3.3-70b-versatile')."
        )
    provider, _, model = model_id.partition(":")
    provider = provider.lower().strip()
    model = model.strip()
    if not model:
        raise ValueError(f"Empty model in {model_id!r}")

    if provider == "openai":
        return OpenAIAdapter(model)
    if provider == "openrouter":
        return OpenRouterAdapter(model)
    if provider == "anthropic":
        return AnthropicAdapter(model)
    if provider == "google":
        return GoogleAdapter(model)
    if provider == "groq":
        return GroqAdapter(model)
    if provider == "mistral":
        return MistralAdapter(model)
    if provider == "mistral-agent":
        return MistralAgentAdapter(model)
    raise ValueError(
        f"Unknown provider {provider!r}. Supported: openai, openrouter, "
        f"anthropic, google, groq, mistral, mistral-agent."
    )
