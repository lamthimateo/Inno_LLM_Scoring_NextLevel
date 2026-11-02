"""Ollama adapter tests. The openai SDK is faked: no network, no Ollama."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import openai
import pytest

from src.adapters import ollama_adapter as oa
from src.adapters.base import UserFacingModelError
from src.adapters.groq_adapter import GroqAdapter
from src.adapters.registry import get_adapter
from src.benchmark.runs import _friendly_model_error

REQUEST = httpx.Request("POST", "http://localhost:11434/v1/chat/completions")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("OLLAMA_BASE_URL", "OLLAMA_TIMEOUT_S", "GROQ_API_KEY"):
        monkeypatch.delenv(var, raising=False)


class FakeCompletions:
    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def reply(text="C1: B", *, usage=None):
    message = SimpleNamespace(content=text)
    return SimpleNamespace(id="resp_1", usage=usage, choices=[SimpleNamespace(message=message)])


def run(adapter, prompt, outcomes, **run_kwargs):
    """Run ``adapter`` against a fake client; return (result_or_exc, completions, OpenAI mock)."""

    completions = FakeCompletions(outcomes)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    openai_cls = MagicMock(return_value=client)
    with patch("openai.OpenAI", openai_cls), patch("time.sleep"):
        try:
            result = adapter.run(prompt, **run_kwargs)
        except Exception as exc:
            result = exc
    return result, completions, openai_cls


# --------------------------------------------------------------------- success


def test_success_returns_reply_and_stores_exact_model_id():
    adapter = oa.OllamaAdapter("llama3.1:8b")

    result, completions, _ = run(adapter, "the prompt", [reply("C1: B\nC2: A")])

    assert result.raw_text == "C1: B\nC2: A"
    assert result.model_id == "ollama:llama3.1:8b"  # tag colon is kept
    assert result.meta["provider"] == "ollama"
    assert result.meta["model"] == "llama3.1:8b"
    assert completions.calls[0]["model"] == "llama3.1:8b"


def test_talks_to_the_openai_compatible_endpoint_without_a_real_key():
    _, _, openai_cls = run(oa.OllamaAdapter("m"), "p", [reply()])

    kwargs = openai_cls.call_args.kwargs
    assert kwargs["base_url"] == "http://localhost:11434/v1"
    assert kwargs["api_key"]  # the SDK needs a non-empty value; Ollama ignores it
    assert kwargs["timeout"] == 600.0


def test_is_always_configured():
    assert oa.OllamaAdapter("m").is_configured() is True


def test_request_matches_a_cloud_adapter_for_fairness(monkeypatch):
    """Same prompt, token limit and temperature as the cloud models."""

    monkeypatch.setenv("GROQ_API_KEY", "k")
    _, cloud, _ = run(GroqAdapter("m"), "same prompt", [reply()])
    _, local, _ = run(oa.OllamaAdapter("m"), "same prompt", [reply()])

    assert local.calls[0] == cloud.calls[0]
    assert local.calls[0]["temperature"] == 0.0
    assert local.calls[0]["max_tokens"] == 2048
    assert local.calls[0]["messages"] == [{"role": "user", "content": "same prompt"}]


# --------------------------------------------------------------- configuration


@pytest.mark.parametrize(
    "configured,expected",
    [
        ("http://ollama:11434", "http://ollama:11434/v1"),
        ("http://ollama:11434/", "http://ollama:11434/v1"),
        ("http://host.docker.internal:11434/v1", "http://host.docker.internal:11434/v1"),
        ("", "http://localhost:11434/v1"),
    ],
)
def test_base_url_comes_from_the_environment(monkeypatch, configured, expected):
    monkeypatch.setenv("OLLAMA_BASE_URL", configured)

    _, _, openai_cls = run(oa.OllamaAdapter("m"), "p", [reply()])

    assert openai_cls.call_args.kwargs["base_url"] == expected


def test_timeout_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("OLLAMA_TIMEOUT_S", "45")

    _, _, openai_cls = run(oa.OllamaAdapter("m"), "p", [reply()])

    assert openai_cls.call_args.kwargs["timeout"] == 45.0


@pytest.mark.parametrize("bad", ["abc", "0", "-5"])
def test_invalid_timeout_falls_back_to_the_default(monkeypatch, bad):
    monkeypatch.setenv("OLLAMA_TIMEOUT_S", bad)

    assert oa.ollama_timeout_s() == oa.DEFAULT_TIMEOUT_S


# --------------------------------------------------------------- failure modes


@pytest.mark.parametrize("content", ["", None, "   \n"])
def test_empty_answer_is_recorded_not_an_error(content):
    result, _, _ = run(oa.OllamaAdapter("m"), "p", [reply(content)])

    assert result.raw_text.strip() == ""
    assert result.meta["empty_response"] is True


def test_non_empty_answer_is_not_flagged_empty():
    result, _, _ = run(oa.OllamaAdapter("m"), "p", [reply("C1: A")])

    assert result.meta["empty_response"] is False


def test_timeout_gives_a_clear_message_after_one_retry():
    timeouts = [openai.APITimeoutError(request=REQUEST)] * 2

    result, completions, _ = run(oa.OllamaAdapter("llama3.1:8b"), "p", timeouts)

    assert isinstance(result, UserFacingModelError)
    assert "did not answer within 600s" in str(result)
    assert "llama3.1:8b" in str(result)
    assert "OLLAMA_TIMEOUT_S" in str(result)
    assert len(completions.calls) == 2


def test_server_not_running_fails_fast_with_a_clear_message():
    down = [openai.APIConnectionError(request=REQUEST)] * 2

    result, completions, _ = run(oa.OllamaAdapter("m"), "p", down)

    assert isinstance(result, UserFacingModelError)
    assert "Ollama is not reachable at http://localhost:11434" in str(result)
    assert "ollama serve" in str(result)
    assert len(completions.calls) == 1  # no retry against a closed port


def test_server_not_running_names_the_configured_address(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")

    result, _, _ = run(oa.OllamaAdapter("m"), "p", [openai.APIConnectionError(request=REQUEST)])

    assert "http://ollama:11434" in str(result)


def test_model_not_installed_says_how_to_pull_it():
    missing = openai.NotFoundError(
        "model 'nope:1b' not found",
        response=httpx.Response(404, request=REQUEST),
        body=None,
    )

    result, completions, _ = run(oa.OllamaAdapter("nope:1b"), "p", [missing])

    assert "ollama pull nope:1b" in str(result)
    assert len(completions.calls) == 1


def test_other_server_errors_are_retried_then_reported():
    errors = [RuntimeError("503 service unavailable")] * 2

    result, completions, _ = run(oa.OllamaAdapter("m"), "p", errors)

    assert isinstance(result, UserFacingModelError)
    assert "Ollama request failed for model 'm' after 2 attempt(s)" in str(result)
    assert len(completions.calls) == 2


# ---------------------------------------------------------------- run metadata


def test_run_metadata_records_the_installed_model_details(monkeypatch):
    installed = oa.Discovery(
        base_url="http://localhost:11434",
        reachable=True,
        models=(
            oa.LocalModel(
                name="llama3.1:8b",
                digest="sha256:abc",
                parameter_size="8.0B",
                quantization="Q4_0",
                family="llama",
                size_bytes=4_700_000_000,
            ),
        ),
    )
    monkeypatch.setattr(oa, "discover_models", lambda *a, **k: installed)

    result, _, _ = run(oa.OllamaAdapter("llama3.1:8b"), "p", [reply()])

    info = result.meta["ollama"]
    assert info["base_url"] == "http://localhost:11434"
    assert info["digest"] == "sha256:abc"
    assert info["quantization"] == "Q4_0"
    assert info["parameter_size"] == "8.0B"


def test_metadata_without_discovery_still_records_the_address():
    result, _, _ = run(oa.OllamaAdapter("m"), "p", [reply()])

    assert result.meta["ollama"] == {"base_url": "http://localhost:11434"}


def test_cut_off_prompt_is_flagged():
    long_prompt = "Q" * 8000  # roughly 2000 tokens
    result, _, _ = run(
        oa.OllamaAdapter("m"), long_prompt, [reply(usage={"prompt_tokens": 300})]
    )

    assert result.meta["ollama"]["context_truncated_suspected"] is True


def test_complete_prompt_is_not_flagged():
    long_prompt = "Q" * 8000
    result, _, _ = run(
        oa.OllamaAdapter("m"), long_prompt, [reply(usage={"prompt_tokens": 1900})]
    )

    assert "context_truncated_suspected" not in result.meta["ollama"]


# -------------------------------------------------------------------- registry


def test_registry_resolves_ollama_ids_with_colons_in_the_model():
    adapter = get_adapter("ollama:llama3.1:8b")

    assert isinstance(adapter, oa.OllamaAdapter)
    assert adapter.model == "llama3.1:8b"
    assert adapter.id() == "ollama:llama3.1:8b"


def test_registry_rejects_an_empty_ollama_model():
    with pytest.raises(ValueError):
        get_adapter("ollama:")


# --------------------------------------------------------- run error rendering


def test_run_error_summary_keeps_ollama_messages_verbatim():
    """The generic rewrite turns anything containing 'timeout' into a vague hint."""

    result, _, _ = run(oa.OllamaAdapter("m"), "p", [openai.APITimeoutError(request=REQUEST)] * 2)

    assert "OLLAMA_TIMEOUT_S" in _friendly_model_error(result)
    # ...while ordinary provider errors are still rewritten.
    assert _friendly_model_error(RuntimeError("request timed out")) == "Provider request timed out."
