import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def load_llm_module():
    root = Path(__file__).resolve().parent

    sys.modules["src"] = types.ModuleType("src")
    sys.modules["src.search"] = types.ModuleType("src.search")

    locale = types.ModuleType("src.search.locale")
    locale.language_name = lambda loc: "English"
    sys.modules["src.search.locale"] = locale

    requests = types.ModuleType("requests")

    class RequestException(Exception):
        pass

    requests.RequestException = RequestException
    requests.post = None
    sys.modules["requests"] = requests

    spec = importlib.util.spec_from_file_location(
        "src.search.llm", root / "src" / "search" / "llm.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["src.search.llm"] = module
    spec.loader.exec_module(module)
    return module


llm = load_llm_module()


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class OpenRouterTests(unittest.TestCase):
    def test_openrouter_request_uses_hosted_api_and_default_model(self):
        response = FakeResponse(
            payload={
                "choices": [
                    {"message": {"content": '["weather tomorrow", "gmail inbox"]'}}
                ]
            }
        )

        with patch("src.search.llm.requests.post", return_value=response) as post:
            queries = llm.generate_queries(
                2,
                "en-US",
                provider="openrouter",
                model="",
                api_key="test-key",
            )

        self.assertEqual(queries, ["weather tomorrow", "gmail inbox"])
        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")
        self.assertEqual(kwargs["headers"]["X-OpenRouter-Title"], "AutoRewarder")
        self.assertEqual(kwargs["json"]["model"], "openai/gpt-5.4-nano")
        self.assertEqual(kwargs["json"]["max_tokens"], llm._max_tokens(2))
        self.assertNotIn("max_completion_tokens", kwargs["json"])

    def test_legacy_9router_alias_uses_openrouter(self):
        response = FakeResponse(
            payload={
                "choices": [
                    {"message": {"content": '["how to reset airpods"]'}}
                ]
            }
        )

        with patch("src.search.llm.requests.post", return_value=response) as post:
            queries = llm.generate_queries(
                1,
                "en-US",
                provider="9router",
                model="",
                api_key="test-key",
            )

        self.assertEqual(queries, ["how to reset airpods"])
        self.assertEqual(
            post.call_args.args[0], "https://openrouter.ai/api/v1/chat/completions"
        )
        self.assertEqual(
            post.call_args.kwargs["json"]["model"], "openai/gpt-5.4-nano"
        )

    def test_openrouter_bad_http_returns_empty_list(self):
        logs = []
        response = FakeResponse(status_code=401, text="bad key")

        with patch("src.search.llm.requests.post", return_value=response):
            queries = llm.generate_queries(
                1,
                "en-US",
                provider="openrouter",
                api_key="bad-key",
                logger=logs.append,
            )

        self.assertEqual(queries, [])
        self.assertIn("LLM (openrouter) request failed", logs[0])

    def test_openrouter_malformed_json_returns_empty_list(self):
        logs = []
        response = FakeResponse(payload=ValueError("Extra data"))

        with patch("src.search.llm.requests.post", return_value=response):
            queries = llm.generate_queries(
                1,
                "en-US",
                provider="openrouter",
                api_key="test-key",
                logger=logs.append,
            )

        self.assertEqual(queries, [])
        self.assertIn("LLM (openrouter) unexpected response", logs[0])

    def test_normalize_query_ignores_case_punctuation_whitespace(self):
        self.assertEqual(
            llm.normalize_query("How to Unclog Toilet?"),
            llm.normalize_query("how to unclog toilet"),
        )
        self.assertEqual(llm.normalize_query("  a..b!! "), "ab")
        self.assertEqual(llm.normalize_query(None), "")

    def test_excluded_queries_are_filtered_from_output(self):
        response = FakeResponse(
            payload={
                "choices": [
                    {
                        "message": {
                            "content": '["how to unclog toilet", "weather tomorrow"]'
                        }
                    }
                ]
            }
        )

        with patch("src.search.llm.requests.post", return_value=response):
            queries = llm.generate_queries(
                2,
                "en-US",
                provider="openrouter",
                api_key="test-key",
                exclude=["How to Unclog Toilet!"],
            )

        self.assertEqual(queries, ["weather tomorrow"])

    def test_prompt_includes_exclude_block_and_today_date(self):
        response = FakeResponse(
            payload={"choices": [{"message": {"content": '["fresh query"]'}}]}
        )

        with patch("src.search.llm.requests.post", return_value=response) as post:
            llm.generate_queries(
                1,
                "en-US",
                provider="openrouter",
                api_key="test-key",
                exclude=["old query one", "old query two"],
            )

        prompt = post.call_args.kwargs["json"]["messages"][0]["content"]
        self.assertIn("Recently used queries", prompt)
        self.assertIn("- old query one", prompt)
        self.assertIn("Today's date:", prompt)


if __name__ == "__main__":
    unittest.main()
