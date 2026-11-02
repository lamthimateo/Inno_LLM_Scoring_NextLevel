"""Characterization tests for the OpenAI-compatible chat adapters (Groq, OpenRouter).

They pin down the behaviour both adapters share, so the common code can be
extracted into one base class without changing what callers see. The
``openai`` SDK is faked: no network, no real keys.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.adapters.groq_adapter import GroqAdapter
from src.adapters.openrouter_adapter import OpenRouterAdapter


KEY_VARS = (
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENROUTER_API",
    "OPENAI_API_KEY",
    "OPENROUTER_HTTP_REFERER",
    "OPENROUTER_APP_TITLE",
)

# (adapter class, provider prefix, env var holding its key, base url, display name)
CASES = [
    pytest.param(GroqAdapter, "groq", "GROQ_API_KEY", "https://api.groq.com/openai/v1", "Groq", id="groq"),
    pytest.param(
        OpenRouterAdapter,
        "openrouter",
        "OPENROUTER_API_KEY",
        "https://openrouter.ai/api/v1",
        "OpenRouter",
        id="openrouter",
    ),
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in KEY_VARS:
        monkeypatch.delenv(var, raising=False)


class FakeCompletions:
    """``client.chat.completions`` that replays queued responses or raises queued errors."""

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def reply(text="C1: B", *, usage=None, response_id="resp_1"):
    message = SimpleNamespace(content=text)
    return SimpleNamespace(id=response_id, usage=usage, choices=[SimpleNamespace(message=message)])


def run_adapter(adapter, prompt, outcomes, **run_kwargs):
    """Run ``adapter`` against a fake client; return (result_or_exc, completions, OpenAI mock)."""

    completions = FakeCompletions(outcomes)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    openai_cls = MagicMock(return_value=client)
    with patch("openai.OpenAI", openai_cls), patch("time.sleep"):
        try:
            result = adapter.run(prompt, **run_kwargs)
        except Exception as exc:  # returned so tests can assert on it
            result = exc
    return result, completions, openai_cls


@pytest.mark.parametrize("cls,provider,key_var,base_url,display", CASES)
def test_success_returns_text_and_metadata(monkeypatch, cls, provider, key_var, base_url, display):
    monkeypatch.setenv(key_var, "test-key")
    adapter = cls("some-model")

    result, completions, _ = run_adapter(
        adapter, "prompt", [reply("C1: B\nC2: A", usage={"total_tokens": 9}, response_id="r42")]
    )

    assert result.model_id == f"{provider}:some-model"
    assert adapter.id() == f"{provider}:some-model"
    assert result.raw_text == "C1: B\nC2: A"
    assert result.meta["provider"] == provider
    assert result.meta["model"] == "some-model"
    assert result.meta["response_id"] == "r42"
    assert result.meta["usage"] == {"total_tokens": 9}
    assert isinstance(result.meta["elapsed_ms"], int)
    assert result.meta["retries"] == 3
    assert len(completions.calls) == 1


@pytest.mark.parametrize("cls,provider,key_var,base_url,display", CASES)
def test_client_is_built_for_the_providers_endpoint(monkeypatch, cls, provider, key_var, base_url, display):
    monkeypatch.setenv(key_var, "test-key")

    _, _, openai_cls = run_adapter(cls("m"), "p", [reply()])

    kwargs = openai_cls.call_args.kwargs
    assert kwargs["api_key"] == "test-key"
    assert kwargs["base_url"] == base_url
    assert kwargs["timeout"] == 120.0


@pytest.mark.parametrize("cls,provider,key_var,base_url,display", CASES)
def test_request_uses_same_prompt_token_limit_and_temperature(monkeypatch, cls, provider, key_var, base_url, display):
    monkeypatch.setenv(key_var, "test-key")

    _, completions, _ = run_adapter(cls("m"), "the prompt", [reply()])

    sent = completions.calls[0]
    assert sent["model"] == "m"
    assert sent["messages"] == [{"role": "user", "content": "the prompt"}]
    assert sent["max_tokens"] == 2048
    assert sent["temperature"] == 0.0


@pytest.mark.parametrize("cls,provider,key_var,base_url,display", CASES)
def test_reasoning_models_never_receive_sampling_params(monkeypatch, cls, provider, key_var, base_url, display):
    monkeypatch.setenv(key_var, "test-key")

    _, completions, _ = run_adapter(cls("o4-mini"), "p", [reply()], temperature=0.7, top_p=0.5)

    sent = completions.calls[0]
    assert "temperature" not in sent
    assert "top_p" not in sent


@pytest.mark.parametrize("cls,provider,key_var,base_url,display", CASES)
def test_retryable_error_is_retried_then_succeeds(monkeypatch, cls, provider, key_var, base_url, display):
    monkeypatch.setenv(key_var, "test-key")

    result, completions, _ = run_adapter(
        cls("m"), "p", [RuntimeError("429 rate limit exceeded"), reply("C1: A")]
    )

    assert result.raw_text == "C1: A"
    assert len(completions.calls) == 2


@pytest.mark.parametrize("cls,provider,key_var,base_url,display", CASES)
def test_non_retryable_error_fails_after_one_call(monkeypatch, cls, provider, key_var, base_url, display):
    monkeypatch.setenv(key_var, "test-key")

    result, completions, _ = run_adapter(cls("m"), "p", [RuntimeError("invalid request body")])

    assert isinstance(result, RuntimeError)
    assert str(result) == (
        f"{display} request failed for model 'm' after 3 attempt(s): invalid request body"
    )
    assert len(completions.calls) == 1


@pytest.mark.parametrize("cls,provider,key_var,base_url,display", CASES)
def test_gives_up_after_max_retries(monkeypatch, cls, provider, key_var, base_url, display):
    monkeypatch.setenv(key_var, "test-key")
    errors = [RuntimeError("503 service unavailable")] * 3

    result, completions, _ = run_adapter(cls("m"), "p", errors)

    assert isinstance(result, RuntimeError)
    assert "after 3 attempt(s)" in str(result)
    assert len(completions.calls) == 3


@pytest.mark.parametrize("cls,provider,key_var,base_url,display", CASES)
def test_missing_key_is_reported_clearly(monkeypatch, cls, provider, key_var, base_url, display):
    adapter = cls("m")

    assert adapter.is_configured() is False
    with pytest.raises(RuntimeError) as exc:
        adapter.run("p")
    assert key_var in str(exc.value)


@pytest.mark.parametrize("cls,provider,key_var,base_url,display", CASES)
def test_empty_reply_becomes_empty_text(monkeypatch, cls, provider, key_var, base_url, display):
    monkeypatch.setenv(key_var, "test-key")

    result, _, _ = run_adapter(cls("m"), "p", [reply(None)])

    assert result.raw_text == ""


def test_openrouter_sends_attribution_headers(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_HTTP_REFERER", "https://example.test")
    monkeypatch.setenv("OPENROUTER_APP_TITLE", "Test Arena")

    _, _, openai_cls = run_adapter(OpenRouterAdapter("m"), "p", [reply()])

    assert openai_cls.call_args.kwargs["default_headers"] == {
        "HTTP-Referer": "https://example.test",
        "X-Title": "Test Arena",
    }


def test_openrouter_falls_back_to_openai_key_for_dev(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "dev-key")

    adapter = OpenRouterAdapter("m")

    assert adapter.is_configured() is True
    _, _, openai_cls = run_adapter(adapter, "p", [reply()])
    assert openai_cls.call_args.kwargs["api_key"] == "dev-key"


def test_groq_sends_no_extra_headers(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")

    _, _, openai_cls = run_adapter(GroqAdapter("m"), "p", [reply()])

    assert "default_headers" not in openai_cls.call_args.kwargs
