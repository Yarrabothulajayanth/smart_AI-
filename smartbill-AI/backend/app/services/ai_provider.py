import asyncio
import json
import math
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


# AI Exceptions
class AIConfigurationError(Exception):
    pass


class AIProviderError(Exception):
    pass


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


# AI Settings
@dataclass(frozen=True)
class AISettings:
    base_url: str
    api_key: str
    chat_model: str
    embedding_model: str
    timeout_seconds: float

    @classmethod
    def from_environment(cls) -> "AISettings":

        timeout_text = os.environ.get(
            "SMARTBILL_AI_TIMEOUT_SECONDS", "25"
        )

        try:
            timeout_seconds = float(timeout_text)
        except ValueError as error:
            raise AIConfigurationError(
                "SMARTBILL_AI_TIMEOUT_SECONDS must be a number."
            ) from error

        if not 1 <= timeout_seconds <= 120:
            raise AIConfigurationError(
                "SMARTBILL_AI_TIMEOUT_SECONDS must be between 1 and 120."
            )

        base_url = os.environ.get(
            "SMARTBILL_AI_BASE_URL", ""
        ).strip().rstrip("/")

        if base_url:
            parsed_url = urlsplit(base_url)

            if (
                parsed_url.scheme not in {"http", "https"}
                or not parsed_url.netloc
                or parsed_url.username is not None
                or parsed_url.password is not None
                or parsed_url.query
                or parsed_url.fragment
            ):
                raise AIConfigurationError(
                    "SMARTBILL_AI_BASE_URL must be an HTTP(S) URL without "
                    "credentials, a query, or a fragment."
                )

            if (
                os.environ.get(
                    "SMARTBILL_ENV", "development"
                ).strip().lower() == "production"
                and parsed_url.scheme != "https"
            ):
                raise AIConfigurationError(
                    "SMARTBILL_AI_BASE_URL must use HTTPS in production."
                )

        return cls(
            base_url=base_url,
            api_key=os.environ.get(
                "SMARTBILL_AI_API_KEY", ""
            ).strip(),
            chat_model=os.environ.get(
                "SMARTBILL_AI_CHAT_MODEL", ""
            ).strip(),
            embedding_model=os.environ.get(
                "SMARTBILL_AI_EMBEDDING_MODEL", ""
            ).strip(),
            timeout_seconds=timeout_seconds,
        )

    @property
    def chat_configured(self) -> bool:
        return bool(self.base_url and self.chat_model)

    @property
    def embeddings_configured(self) -> bool:
        return self.chat_configured and bool(self.embedding_model)


# OpenAI Compatible AI Provider
class OpenAICompatibleProvider:

    def __init__(
        self,
        settings: AISettings | None = None
    ) -> None:
        self.settings = settings or AISettings.from_environment()

    # Chat Method
    async def chat(
        self,
        messages: list[dict[str, str]],
        json_mode: bool = False,
    ) -> str:

        if not self.settings.chat_configured:
            raise AIConfigurationError(
                "Configure SMARTBILL_AI_BASE_URL and SMARTBILL_AI_CHAT_MODEL "
                "to enable the assistant."
            )

        payload = {
            "model": self.settings.chat_model,
            "messages": messages,
            "temperature": 0,
        }

        # Enable JSON response when requested
        if json_mode:
            payload["response_format"] = {
                "type": "json_object"
            }

        response = await asyncio.to_thread(
            self._post_json,
            "/chat/completions",
            payload
        )

        choices = response.get("choices")

        if not isinstance(choices, list) or not choices:
            raise AIProviderError(
                "The AI provider returned no chat response."
            )

        choice = choices[0]

        if not isinstance(choice, dict):
            raise AIProviderError(
                "The AI provider returned an invalid chat response."
            )

        message = choice.get("message")

        if not isinstance(message, dict):
            raise AIProviderError(
                "The AI provider returned an invalid chat response."
            )

        content = message.get("content")

        if not isinstance(content, str) or not content.strip():
            raise AIProviderError(
                "The AI provider returned an empty chat response."
            )

        return content.strip()

    # Embedding Method
    async def embed(
        self,
        texts: list[str]
    ) -> list[list[float]]:

        if not self.settings.embeddings_configured:
            raise AIConfigurationError(
                "Configure SMARTBILL_AI_EMBEDDING_MODEL to enable document "
                "ingestion and semantic search."
            )

        if not texts:
            return []

        payload = {
            "model": self.settings.embedding_model,
            "input": texts,
        }

        response = await asyncio.to_thread(
            self._post_json,
            "/embeddings",
            payload
        )

        raw_data = response.get("data")

        if (
            not isinstance(raw_data, list)
            or len(raw_data) != len(texts)
        ):
            raise AIProviderError(
                "The AI provider returned invalid embeddings."
            )

        ordered: list[list[float] | None] = [
            None
        ] * len(texts)

        for fallback_index, entry in enumerate(raw_data):

            if not isinstance(entry, dict):
                raise AIProviderError(
                    "The AI provider returned invalid embeddings."
                )

            index = entry.get("index", fallback_index)
            vector = entry.get("embedding")

            if (
                not isinstance(index, int)
                or index < 0
                or index >= len(texts)
                or not isinstance(vector, list)
                or not vector
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    for value in vector
                )
            ):
                raise AIProviderError(
                    "The AI provider returned invalid embeddings."
                )

            ordered[index] = [
                float(value) for value in vector
            ]

        if any(vector is None for vector in ordered):
            raise AIProviderError(
                "The AI provider returned incomplete embeddings."
            )

        return [
            vector for vector in ordered
            if vector is not None
        ]

    # HTTP Request Method
    def _post_json(
        self,
        endpoint: str,
        payload: dict[str, object]
    ) -> dict[str, object]:

        if not self.settings.base_url:
            raise AIConfigurationError(
                "SMARTBILL_AI_BASE_URL is not configured."
            )

        body = json.dumps(
            payload,
            ensure_ascii=False
        ).encode("utf-8")

        headers = {
            "Content-Type": "application/json"
        }

        if self.settings.api_key:
            headers["Authorization"] = (
                f"Bearer {self.settings.api_key}"
            )

        request = Request(
            f"{self.settings.base_url}{endpoint}",
            data=body,
            headers=headers,
            method="POST",
        )

        try:
            opener = build_opener(_NoRedirectHandler)

            with opener.open(
                request,
                timeout=self.settings.timeout_seconds
            ) as response:

                response_body = response.read(1_000_001)

        except HTTPError as error:
            raise AIProviderError(
                f"The AI provider returned HTTP {error.code}."
            ) from error

        except (TimeoutError, URLError) as error:
            raise AIProviderError(
                "The AI provider could not be reached or timed out."
            ) from error

        if len(response_body) > 1_000_000:
            raise AIProviderError(
                "The AI provider response exceeded the size limit."
            )

        try:
            decoded = json.loads(
                response_body.decode("utf-8")
            )

        except (
            UnicodeDecodeError,
            json.JSONDecodeError
        ) as error:

            raise AIProviderError(
                "The AI provider returned invalid JSON."
            ) from error

        if not isinstance(decoded, dict):
            raise AIProviderError(
                "The AI provider returned an invalid response."
            )

        return decoded