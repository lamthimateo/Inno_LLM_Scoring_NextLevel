"""Ollama adapter — local models through Ollama's OpenAI-compatible API.

Ollama serves ``POST /v1/chat/completions`` next to its native API, so this
adapter is a thin subclass of :class:`~src.adapters._openai_compat.OpenAICompatAdapter`:
same prompt, same token limit, same temperature as every cloud model.

Model ids follow the usual ``provider:model`` shape. The model part may
itself contain a colon (an Ollama tag), e.g. ``ollama:llama3.1:8b``.

Configuration (environment)
---------------------------

``OLLAMA_BASE_URL``  Server address. Default ``http://localhost:11434``.
                     In Docker use ``http://host.docker.internal:11434``
                     (Ollama on the host) or ``http://ollama:11434`` (the
                     optional ``local`` Compose profile).
``OLLAMA_TIMEOUT_S`` Per-request timeout in seconds. Default 600: the first
                     request has to load the model into memory.

Model discovery
---------------

:func:`discover_models` reads the installed models from ``GET /api/tags``.
It never raises: an unreachable server comes back as a
:class:`Discovery` with ``reachable=False`` and a message, so the UI can show
it instead of crashing. Results are cached for a few seconds so page loads
do not wait on a dead server.

Context window
--------------

Ollama evaluates a prompt only up to its context window and the
OpenAI-compatible endpoint cannot raise it per request. A long benchmark
prompt can therefore be cut off without any error. The adapter records a
heuristic ``ollama.context_truncated_suspected`` flag in the run metadata
when the evaluated prompt is far shorter than the prompt that was sent.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

from ._openai_compat import OpenAICompatAdapter
from .base import UserFacingModelError

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_TIMEOUT_S = 600.0
DISCOVERY_TIMEOUT_S = 1.5

# Discovery cache lifetimes (seconds). Failures are cached shorter so a
# server that was just started shows up quickly.
_OK_TTL_S = 15.0
_FAIL_TTL_S = 5.0

# Context-truncation heuristic: a prompt that Ollama evaluated at less than
# this share of the tokens its length suggests (about 4 characters per
# token) was most likely cut by the context window.
_CHARS_PER_TOKEN = 4
_TRUNCATION_RATIO = 0.5


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------


def ollama_base_url() -> str:
    """Server address from ``OLLAMA_BASE_URL`` (without trailing slash or ``/v1``)."""

    raw = (os.getenv("OLLAMA_BASE_URL") or "").strip() or DEFAULT_BASE_URL
    raw = raw.rstrip("/")
    if raw.endswith("/v1"):
        raw = raw[: -len("/v1")]
    return raw


def ollama_timeout_s() -> float:
    try:
        value = float(os.getenv("OLLAMA_TIMEOUT_S", ""))
    except ValueError:
        return DEFAULT_TIMEOUT_S
    return value if value > 0 else DEFAULT_TIMEOUT_S


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LocalModel:
    """One model installed in Ollama, as reported by ``/api/tags``."""

    name: str
    size_bytes: Optional[int] = None
    parameter_size: Optional[str] = None
    quantization: Optional[str] = None
    family: Optional[str] = None
    digest: Optional[str] = None
    modified_at: Optional[str] = None

    @property
    def model_id(self) -> str:
        return f"ollama:{self.name}"

    @property
    def size_label(self) -> str:
        if not self.size_bytes:
            return ""
        gb = self.size_bytes / 1_000_000_000
        return f"{gb:.1f} GB" if gb >= 1 else f"{self.size_bytes / 1_000_000:.0f} MB"


@dataclass(frozen=True)
class Discovery:
    """Outcome of asking Ollama which models are installed."""

    base_url: str
    reachable: bool
    models: tuple[LocalModel, ...] = ()
    error: Optional[str] = None


def parse_tags(payload: Any) -> tuple[LocalModel, ...]:
    """Turn a ``/api/tags`` response body into :class:`LocalModel` rows.

    Tolerant by design: entries without a usable name are skipped and every
    detail field is optional.
    """

    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        raise ValueError("response has no 'models' list")

    models: list[LocalModel] = []
    for entry in payload["models"]:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("model")
        if not isinstance(name, str) or not name.strip():
            continue
        details = entry.get("details") if isinstance(entry.get("details"), dict) else {}
        size = entry.get("size")
        models.append(
            LocalModel(
                name=name.strip(),
                size_bytes=size if isinstance(size, int) else None,
                parameter_size=details.get("parameter_size") or None,
                quantization=details.get("quantization_level") or None,
                family=details.get("family") or None,
                digest=entry.get("digest") or None,
                modified_at=entry.get("modified_at") or None,
            )
        )
    return tuple(sorted(models, key=lambda m: m.name))


_cache: Dict[str, tuple[float, Discovery]] = {}
_cache_lock = threading.Lock()


def clear_discovery_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _fetch(base_url: str, timeout_s: float, transport: Optional[httpx.BaseTransport]) -> Discovery:
    try:
        with httpx.Client(timeout=timeout_s, transport=transport) as client:
            response = client.get(f"{base_url}/api/tags")
    except httpx.TimeoutException:
        return Discovery(base_url, False, error=f"Ollama at {base_url} did not answer in time.")
    except httpx.ConnectError:
        return Discovery(base_url, False, error=f"Ollama is not reachable at {base_url}.")
    except httpx.HTTPError as exc:
        return Discovery(
            base_url, False, error=f"Could not talk to Ollama at {base_url} ({type(exc).__name__})."
        )

    if response.status_code != 200:
        return Discovery(
            base_url, False, error=f"Ollama at {base_url} answered HTTP {response.status_code}."
        )
    try:
        models = parse_tags(response.json())
    except ValueError:
        return Discovery(base_url, False, error=f"Ollama at {base_url} returned an unexpected response.")
    return Discovery(base_url, True, models)


def discover_models(
    base_url: Optional[str] = None,
    *,
    timeout_s: float = DISCOVERY_TIMEOUT_S,
    transport: Optional[httpx.BaseTransport] = None,
    use_cache: bool = True,
) -> Discovery:
    """List the models installed in Ollama. Never raises.

    ``transport`` lets tests inject ``httpx.MockTransport``; calls with a
    custom transport bypass the cache.
    """

    url = (base_url or ollama_base_url()).rstrip("/")
    cacheable = use_cache and transport is None
    now = time.monotonic()
    if cacheable:
        with _cache_lock:
            hit = _cache.get(url)
        if hit is not None and hit[0] > now:
            return hit[1]

    result = _fetch(url, timeout_s, transport)
    if cacheable:
        ttl = _OK_TTL_S if result.reachable else _FAIL_TTL_S
        with _cache_lock:
            _cache[url] = (now + ttl, result)
    return result


def describe_model(name: str, base_url: Optional[str] = None) -> Dict[str, Any]:
    """Installed-model details worth recording with a run (empty if unknown)."""

    found = next((m for m in discover_models(base_url).models if m.name == name), None)
    if found is None:
        return {}
    details = {
        "digest": found.digest,
        "parameter_size": found.parameter_size,
        "quantization": found.quantization,
        "family": found.family,
        "size_bytes": found.size_bytes,
        "modified_at": found.modified_at,
    }
    return {k: v for k, v in details.items() if v is not None}


# ---------------------------------------------------------------------------
# adapter
# ---------------------------------------------------------------------------


class OllamaAdapter(OpenAICompatAdapter):
    provider = "ollama"
    display_name = "Ollama"
    default_max_retries = 2
    error_class = UserFacingModelError

    def __init__(self, model: str, base_url: Optional[str] = None):
        self._root = (base_url or ollama_base_url()).rstrip("/")
        super().__init__(model)
        self.default_timeout_s = ollama_timeout_s()

    # Ollama needs no key, but the OpenAI SDK insists on a non-empty one.
    def resolve_api_key(self) -> Optional[str]:
        return "ollama"

    def missing_key_message(self) -> str:  # pragma: no cover - key is never missing
        return "Ollama does not need an API key."

    def get_base_url(self) -> str:
        return f"{self._root}/v1"

    def is_retryable(self, exc: Exception) -> bool:
        import openai

        if isinstance(exc, openai.APITimeoutError):
            return True
        if isinstance(exc, openai.APIConnectionError):
            return False  # nothing is listening: fail fast with a clear message
        return super().is_retryable(exc)

    def describe_failure(self, exc: Exception, attempts: int, timeout_s: float) -> str:
        import openai

        if isinstance(exc, openai.APITimeoutError):
            return (
                f"Ollama did not answer within {timeout_s:g}s for model '{self.model}'. "
                "A cold model load can take a while; allow more time in the .env setting "
                "OLLAMA_TIMEOUT_S."
            )
        if isinstance(exc, openai.APIConnectionError):
            return (
                f"Ollama is not reachable at {self._root}. "
                "Start it (ollama serve) or check OLLAMA_BASE_URL."
            )
        if isinstance(exc, openai.NotFoundError):
            return (
                f"Ollama does not have the model '{self.model}'. "
                f"Install it with: ollama pull {self.model}"
            )
        return super().describe_failure(exc, attempts, timeout_s)

    def extra_meta(self, resp: Any, raw_text: str, prompt: str) -> Dict[str, Any]:
        info: Dict[str, Any] = {"base_url": self._root}
        info.update(describe_model(self.model, self._root))

        usage = getattr(resp, "usage", None)
        prompt_tokens = (
            usage.get("prompt_tokens") if isinstance(usage, dict) else getattr(usage, "prompt_tokens", None)
        )
        if isinstance(prompt_tokens, int):
            expected = len(prompt) / _CHARS_PER_TOKEN
            if prompt_tokens < expected * _TRUNCATION_RATIO:
                info["context_truncated_suspected"] = True
                log.warning(
                    "ollama.context_truncated_suspected model=%s prompt_chars=%d prompt_tokens=%d",
                    self.model,
                    len(prompt),
                    prompt_tokens,
                )

        return {"ollama": info, "empty_response": not raw_text.strip()}
