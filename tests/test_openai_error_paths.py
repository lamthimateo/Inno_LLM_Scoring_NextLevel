import unittest
from unittest.mock import patch

from src.adapters.openai_adapter import OpenAIAdapter


class TestOpenAIAdapterErrors(unittest.TestCase):
    def test_missing_api_key_raises_clear_error(self):
        with patch("os.getenv", return_value=None):
            a = OpenAIAdapter(model="gpt-test")
            with self.assertRaises(RuntimeError) as cm:
                a.run("hi", max_retries=1)
            self.assertIn("OPENAI_API_KEY", str(cm.exception))


if __name__ == "__main__":
    unittest.main()

