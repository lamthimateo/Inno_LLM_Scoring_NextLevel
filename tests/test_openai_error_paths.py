import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from src.adapters.openai_adapter import OpenAIAdapter


def _install_fake_openai(captured: dict) -> tuple:
    """Install a fake ``openai`` module so ``from openai import OpenAI`` works.

    Returns the (module, OpenAI class) it installed. The created client
    records the kwargs passed to ``client.responses.create(...)`` into
    ``captured`` and returns a minimal response object.
    """
    response = types.SimpleNamespace(
        output_text="ok",
        id="resp_test",
        usage={"input_tokens": 1, "output_tokens": 1},
        output=[],
    )

    def _create(**kwargs):
        captured.clear()
        captured.update(kwargs)
        return response

    fake_responses = MagicMock()
    fake_responses.create.side_effect = _create
    fake_client = MagicMock()
    fake_client.responses = fake_responses

    fake_module = types.ModuleType("openai")
    fake_module.OpenAI = MagicMock(return_value=fake_client)
    return fake_module, fake_client


class TestOpenAIAdapterErrors(unittest.TestCase):
    def test_missing_api_key_raises_clear_error(self):
        with patch("os.getenv", return_value=None):
            a = OpenAIAdapter(model="gpt-test")
            with self.assertRaises(RuntimeError) as cm:
                a.run("hi", max_retries=1)
            self.assertIn("OPENAI_API_KEY", str(cm.exception))


class TestTemperatureOmissionForReasoningModels(unittest.TestCase):
    def _run(self, model: str) -> dict:
        captured: dict = {}
        fake_module, _ = _install_fake_openai(captured)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False), \
             patch.dict(sys.modules, {"openai": fake_module}):
            a = OpenAIAdapter(model=model)
            a.run("hello", max_retries=1)
        return captured

    def test_o_series_model_omits_temperature(self):
        kwargs = self._run("o4-mini")
        self.assertEqual(kwargs.get("model"), "o4-mini")
        self.assertEqual(kwargs.get("input"), "hello")
        self.assertNotIn("temperature", kwargs)
        self.assertNotIn("top_p", kwargs)

    def test_gpt_model_includes_temperature(self):
        kwargs = self._run("gpt-5.5")
        self.assertEqual(kwargs.get("model"), "gpt-5.5")
        self.assertIn("temperature", kwargs)


if __name__ == "__main__":
    unittest.main()

