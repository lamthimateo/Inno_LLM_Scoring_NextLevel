"""Model discovery against Ollama's /api/tags, with mocked HTTP only."""

from __future__ import annotations

import httpx
import pytest

from src.adapters import ollama_adapter as oa
from src.adapters.registry import GROUP_LOCAL, local_catalog_entries

# The real function, captured at import time (the autouse conftest fixture
# replaces the module attribute with an "unreachable" stub for every test).
real_discover = oa.discover_models

TAGS = {
    "models": [
        {
            "name": "qwen2.5:7b",
            "model": "qwen2.5:7b",
            "modified_at": "2026-09-20T10:00:00Z",
            "size": 4_683_087_332,
            "digest": "sha256:845dbda0",
            "details": {
                "format": "gguf",
                "family": "qwen2",
                "parameter_size": "7.6B",
                "quantization_level": "Q4_K_M",
            },
        },
        {
            "name": "llama3.1:8b",
            "size": 4_920_753_328,
            "digest": "sha256:46e0c10c",
            "details": {"family": "llama", "parameter_size": "8.0B", "quantization_level": "Q4_0"},
        },
    ]
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)


def transport(handler):
    return httpx.MockTransport(handler)


# --------------------------------------------------------------------- parsing


def test_parse_tags_reads_names_sizes_and_details_sorted():
    models = oa.parse_tags(TAGS)

    assert [m.name for m in models] == ["llama3.1:8b", "qwen2.5:7b"]
    qwen = models[1]
    assert qwen.model_id == "ollama:qwen2.5:7b"
    assert qwen.parameter_size == "7.6B"
    assert qwen.quantization == "Q4_K_M"
    assert qwen.family == "qwen2"
    assert qwen.digest == "sha256:845dbda0"
    assert qwen.size_bytes == 4_683_087_332
    assert qwen.size_label == "4.7 GB"


def test_parse_tags_tolerates_missing_and_odd_fields():
    payload = {
        "models": [
            {"model": "only-model-key:1b"},  # no "name"
            {"name": ""},  # unusable
            {"size": 5},  # no name at all
            "not a dict",
            {"name": "bare:latest", "details": "oops", "size": "big"},
        ]
    }

    models = oa.parse_tags(payload)

    assert [m.name for m in models] == ["bare:latest", "only-model-key:1b"]
    assert all(m.size_bytes is None and m.digest is None for m in models)


@pytest.mark.parametrize("payload", [None, [], {"foo": 1}, {"models": "x"}])
def test_parse_tags_rejects_unexpected_shapes(payload):
    with pytest.raises(ValueError):
        oa.parse_tags(payload)


def test_size_label_for_small_and_unknown_sizes():
    assert oa.LocalModel("tiny", size_bytes=274_000_000).size_label == "274 MB"
    assert oa.LocalModel("unknown").size_label == ""


# ------------------------------------------------------------------- discovery


def test_discover_lists_installed_models():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url)))
        return httpx.Response(200, json=TAGS)

    result = real_discover("http://localhost:11434/", transport=transport(handler))

    assert result.reachable is True
    assert result.error is None
    assert result.base_url == "http://localhost:11434"
    assert [m.name for m in result.models] == ["llama3.1:8b", "qwen2.5:7b"]
    assert seen == [("GET", "http://localhost:11434/api/tags")]


def test_discover_uses_the_configured_address(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    urls = []

    def handler(request):
        urls.append(str(request.url))
        return httpx.Response(200, json={"models": []})

    result = real_discover(transport=transport(handler))

    assert urls == ["http://ollama:11434/api/tags"]
    assert result.reachable is True and result.models == ()


def test_server_not_running_is_reported_not_raised():
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    result = real_discover("http://localhost:11434", transport=transport(handler))

    assert result.reachable is False
    assert result.models == ()
    assert result.error == "Ollama is not reachable at http://localhost:11434."


def test_slow_server_is_reported_not_raised():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    result = real_discover("http://localhost:11434", transport=transport(handler))

    assert result.reachable is False
    assert "did not answer in time" in result.error


@pytest.mark.parametrize(
    "response,fragment",
    [
        (httpx.Response(500, text="boom"), "answered HTTP 500"),
        (httpx.Response(404, text="nope"), "answered HTTP 404"),
        (httpx.Response(200, text="not json"), "unexpected response"),
        (httpx.Response(200, json={"foo": 1}), "unexpected response"),
    ],
)
def test_bad_answers_are_reported_not_raised(response, fragment):
    result = real_discover("http://x:1", transport=transport(lambda request: response))

    assert result.reachable is False
    assert fragment in result.error


def test_empty_model_list_is_reachable_but_has_no_models():
    result = real_discover(
        "http://x:1", transport=transport(lambda request: httpx.Response(200, json={"models": []}))
    )

    assert result.reachable is True
    assert result.models == ()


# ---------------------------------------------------------------------- caching


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def counted_fetch(monkeypatch):
    """Replace the HTTP call with a counter and a controllable clock."""

    oa.clear_discovery_cache()
    clock = Clock()
    monkeypatch.setattr(oa.time, "monotonic", clock)
    state = {"calls": 0, "ok": True}

    def fake_fetch(base_url, timeout_s, transport_):
        state["calls"] += 1
        if state["ok"]:
            return oa.Discovery(base_url, True, (oa.LocalModel("m:1b"),))
        return oa.Discovery(base_url, False, error="down")

    monkeypatch.setattr(oa, "_fetch", fake_fetch)
    yield state, clock
    oa.clear_discovery_cache()


def test_successful_discovery_is_cached_briefly(counted_fetch):
    state, clock = counted_fetch

    real_discover("http://c:1")
    real_discover("http://c:1")
    assert state["calls"] == 1

    clock.now += oa._OK_TTL_S + 1
    real_discover("http://c:1")
    assert state["calls"] == 2


def test_failures_are_cached_shorter_so_a_started_server_shows_up(counted_fetch):
    state, clock = counted_fetch
    state["ok"] = False

    assert real_discover("http://c:1").reachable is False
    clock.now += oa._FAIL_TTL_S + 1
    state["ok"] = True

    assert real_discover("http://c:1").reachable is True
    assert state["calls"] == 2


def test_cache_is_per_address(counted_fetch):
    state, _ = counted_fetch

    real_discover("http://a:1")
    real_discover("http://b:1")

    assert state["calls"] == 2


def test_use_cache_false_always_asks(counted_fetch):
    state, _ = counted_fetch

    real_discover("http://c:1", use_cache=False)
    real_discover("http://c:1", use_cache=False)

    assert state["calls"] == 2


# ------------------------------------------------------------- catalog entries


def test_discovered_models_become_local_catalog_entries():
    discovery = oa.Discovery("http://x:1", True, oa.parse_tags(TAGS))

    entries = local_catalog_entries(discovery)

    assert [e.id for e in entries] == ["ollama:llama3.1:8b", "ollama:qwen2.5:7b"]
    assert all(e.group == GROUP_LOCAL and e.provider == "ollama" for e in entries)
    assert not any(e.is_default for e in entries)  # never pre-selected
    assert all(e.requires_env == "" for e in entries)


def test_unreachable_server_gives_no_local_entries():
    assert local_catalog_entries(oa.Discovery("http://x:1", False, error="down")) == []
