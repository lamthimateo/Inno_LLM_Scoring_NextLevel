"""Adapter registry — resolve a model ID string into a runnable adapter.

Model IDs use a ``provider:model`` form, e.g.::

    openai:gpt-5.5
    openrouter:openai/gpt-5.5
    openrouter:anthropic/claude-sonnet-4

The web UI offers a small curated list (the ``DEFAULT_MODELS`` below) but
nothing prevents an admin from typing any other valid model string.

Picking the preset:

- If ``OPENROUTER_API_KEY`` is set we route through OpenRouter so we can
  compare across providers (OpenAI / Anthropic / Google / DeepSeek) with a
  single key. OpenRouter mirrors the OpenAI Chat Completions API, so we
  reuse the OpenAI Python SDK with a custom ``base_url``.
- If only ``OPENAI_API_KEY`` is set we fall back to four OpenAI variants
  hitting the Responses API directly. This is what the local ``.env``
  ships with today (no OpenRouter key configured) so we default to it.

Model ids in the preset are 2026 OpenAI ids verified against the public
docs at ``https://developers.openai.com/api/docs/models/``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List

from src.adapters.base import ModelAdapter
from src.adapters.openai_adapter import OpenAIAdapter
from src.adapters.openrouter_adapter import OpenRouterAdapter


# ---------------------------------------------------------------------------
# Curated catalog
# ---------------------------------------------------------------------------
#
# The catalog is the single source of truth for the model picker in the
# New-run form. Each entry maps a wire id (``provider:model``) to a
# human-readable label and the env var that must be set for the adapter to
# be runnable. The form validates submitted ids against this list so the
# user can't smuggle in arbitrary strings via the UI.
#
# The CLI / programmatic API is unaffected — it still accepts any
# ``provider:model`` resolvable by :func:`get_adapter`.

# Display groups in the dropdown. Order matters: OpenAI direct comes first
# because that's the zero-config default for a fresh checkout.
GROUP_OPENAI_DIRECT = "OpenAI direct"
GROUP_OPENROUTER = "OpenRouter cross-provider"


@dataclass(frozen=True)
class CatalogEntry:
    """One picker option in the curated model catalog.

    Attributes
    ----------
    id:
        Wire id sent to the provider (``provider:model``).
    label:
        Human-readable name shown in the dropdown.
    provider:
        Lowercase provider tag (``openai`` / ``openrouter``).
    group:
        Display group used to render the ``<optgroup>``.
    requires_env:
        Env var that must be set for this entry to be runnable.
    is_default:
        Pre-selected when the form renders. The runtime preset is the
        union of all entries flagged ``is_default``.
    """

    id: str
    label: str
    provider: str
    group: str
    requires_env: str
    is_default: bool


def _build_catalog() -> List[CatalogEntry]:
    """Compose the catalog. ``is_default`` follows the legacy preset rule:

    - If ``OPENROUTER_API_KEY`` is set the 4 OpenRouter entries are the
      default selection (cross-provider comparison).
    - Otherwise the 4 OpenAI direct entries are the default.
    """

    openrouter_is_default = bool(os.getenv("OPENROUTER_API_KEY"))

    return [
        CatalogEntry(
            id="openai:gpt-5.5",
            label="GPT-5.5",
            provider="openai",
            group=GROUP_OPENAI_DIRECT,
            requires_env="OPENAI_API_KEY",
            is_default=not openrouter_is_default,
        ),
        CatalogEntry(
            id="openai:gpt-5.4-mini",
            label="GPT-5.4 mini",
            provider="openai",
            group=GROUP_OPENAI_DIRECT,
            requires_env="OPENAI_API_KEY",
            is_default=not openrouter_is_default,
        ),
        CatalogEntry(
            id="openai:gpt-5-mini",
            label="GPT-5 mini",
            provider="openai",
            group=GROUP_OPENAI_DIRECT,
            requires_env="OPENAI_API_KEY",
            is_default=not openrouter_is_default,
        ),
        CatalogEntry(
            id="openai:o4-mini",
            label="o4 mini",
            provider="openai",
            group=GROUP_OPENAI_DIRECT,
            requires_env="OPENAI_API_KEY",
            is_default=not openrouter_is_default,
        ),
        CatalogEntry(
            id="openrouter:openai/gpt-5.5",
            label="GPT-5.5 (via OpenRouter)",
            provider="openrouter",
            group=GROUP_OPENROUTER,
            requires_env="OPENROUTER_API_KEY",
            is_default=openrouter_is_default,
        ),
        CatalogEntry(
            id="openrouter:anthropic/claude-sonnet-4.5",
            label="Claude Sonnet 4.5",
            provider="openrouter",
            group=GROUP_OPENROUTER,
            requires_env="OPENROUTER_API_KEY",
            is_default=openrouter_is_default,
        ),
        CatalogEntry(
            id="openrouter:google/gemini-2.5-pro",
            label="Gemini 2.5 Pro",
            provider="openrouter",
            group=GROUP_OPENROUTER,
            requires_env="OPENROUTER_API_KEY",
            is_default=openrouter_is_default,
        ),
        CatalogEntry(
            id="openrouter:deepseek/deepseek-v3.2",
            label="DeepSeek V3.2",
            provider="openrouter",
            group=GROUP_OPENROUTER,
            requires_env="OPENROUTER_API_KEY",
            is_default=openrouter_is_default,
        ),
    ]


# Resolved at import time — restart the app after rotating provider keys.
MODEL_CATALOG: List[CatalogEntry] = _build_catalog()


def catalog_by_id() -> Dict[str, CatalogEntry]:
    """Fast id -> :class:`CatalogEntry` lookup for route validation."""

    return {e.id: e for e in MODEL_CATALOG}


def catalog_grouped() -> List[tuple[str, List[CatalogEntry]]]:
    """Catalog as ``[(group_label, [entry, ...]), ...]`` for ``<optgroup>``s.

    Group order preserves first-seen order in :data:`MODEL_CATALOG`.
    """

    groups: dict[str, list[CatalogEntry]] = {}
    for entry in MODEL_CATALOG:
        groups.setdefault(entry.group, []).append(entry)
    return list(groups.items())


def group_is_available(group: str) -> bool:
    """Whether every entry in ``group`` has its ``requires_env`` set.

    Used by the template to gray out the OpenRouter optgroup when no
    ``OPENROUTER_API_KEY`` is configured.
    """

    entries = [e for e in MODEL_CATALOG if e.group == group]
    if not entries:
        return False
    return all(os.getenv(e.requires_env) for e in entries)


def default_catalog_ids() -> List[str]:
    """The runtime preset — every catalog entry currently flagged default."""

    return [e.id for e in MODEL_CATALOG if e.is_default]


# Backwards-compatible aliases for code that still imports the old preset
# constants. Kept thin on purpose; new code should use the catalog helpers.
OPENROUTER_PRESET: List[str] = [
    e.id for e in MODEL_CATALOG if e.group == GROUP_OPENROUTER
]
OPENAI_PRESET: List[str] = [
    e.id for e in MODEL_CATALOG if e.group == GROUP_OPENAI_DIRECT
]
DEFAULT_MODELS: List[str] = default_catalog_ids()


def get_adapter(model_id: str) -> ModelAdapter:
    """Resolve ``provider:model`` into a configured :class:`ModelAdapter`."""

    if ":" not in model_id:
        raise ValueError(
            f"Invalid model id {model_id!r}. Expected 'provider:model' "
            f"(e.g. 'openai:gpt-5.5' or 'openrouter:openai/gpt-5.5')."
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
    raise ValueError(
        f"Unknown provider {provider!r}. Supported: openai, openrouter."
    )
