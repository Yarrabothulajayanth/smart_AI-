import json
import unittest
from unittest.mock import patch
from urllib.request import Request

from app.services.ai_provider import (
    AIConfigurationError,
    AISettings,
    OpenAICompatibleProvider,
    _NoRedirectHandler,
)


class MockResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "MockResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self.body


class MockOpener:
    def __init__(self, response: MockResponse) -> None:
        self.response = response
        self.request: Request | None = None
        self.timeout: float | None = None

    def open(self, request: Request, timeout: float) -> MockResponse:
        self.request = request
        self.timeout = timeout
        return self.response


class CompatibleProviderTest(unittest.IsolatedAsyncioTestCase):
    async def test_chat_uses_configured_model_and_bearer_key(self) -> None:
        provider = OpenAICompatibleProvider(
            AISettings(
                base_url="https://provider.example/v1",
                api_key="test-key",
                chat_model="test-chat",
                embedding_model="test-embedding",
                timeout_seconds=5,
            )
        )
        response = MockResponse(
            {"choices": [{"message": {"content": '{"intent":"general"}'}}]}
        )
        opener = MockOpener(response)
        with patch(
            "app.services.ai_provider.build_opener", return_value=opener
        ) as build_opener:
            answer = await provider.chat(
                [{"role": "user", "content": "hello"}]
            )
        self.assertEqual(answer, '{"intent":"general"}')
        request = opener.request
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(
            request.full_url, "https://provider.example/v1/chat/completions"
        )
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        self.assertIn(_NoRedirectHandler, build_opener.call_args.args)
        self.assertEqual(opener.timeout, 5)

    async def test_embeddings_are_returned_in_input_order(self) -> None:
        provider = OpenAICompatibleProvider(
            AISettings(
                base_url="https://provider.example/v1",
                api_key="",
                chat_model="test-chat",
                embedding_model="test-embedding",
                timeout_seconds=5,
            )
        )
        response = MockResponse(
            {
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ]
            }
        )
        opener = MockOpener(response)
        with patch("app.services.ai_provider.build_opener", return_value=opener):
            vectors = await provider.embed(["first", "second"])
        self.assertEqual(vectors, [[1.0, 0.0], [0.0, 1.0]])

    def test_production_provider_url_requires_https(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "SMARTBILL_ENV": "production",
                "SMARTBILL_AI_BASE_URL": "http://provider.example/v1",
            },
        ):
            with self.assertRaises(AIConfigurationError):
                AISettings.from_environment()
