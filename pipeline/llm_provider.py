"""Abstract LLM provider interface and OpenAI-compatible base implementation.

Provides the core data structures (:class:`Usage`, :class:`LLMResponse`),
the abstract interface :class:`LLMProvider`, and a concrete HTTP-based
:class:`OpenAICompatibleProvider` that subclasses can extend.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Usage:
    """Token usage statistics for a single API call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""

    content: str
    usage: Usage


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """Abstract base class for LLM providers.

    Subclasses must implement :meth:`chat`, :meth:`estimate_tokens`, and
    :meth:`calculate_cost`.
    """

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send a chat completion request and return a unified response.

        Args:
            messages: List of message dicts with ``role`` and ``content`` keys.
            model: Model name to use. Uses the provider default if *None*.
            temperature: Sampling temperature (0.0 to 2.0).
            max_tokens: Maximum tokens in the response.
            **kwargs: Additional parameters passed to the API.

        Returns:
            LLMResponse with content and usage statistics.
        """
        ...

    @abstractmethod
    def estimate_tokens(self, text: str) -> int:
        """Roughly estimate the number of tokens in a given text.

        Args:
            text: Input text string.

        Returns:
            Estimated token count.
        """
        ...

    @abstractmethod
    def calculate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str | None = None,
    ) -> float:
        """Calculate the USD cost for a given token usage.

        Args:
            prompt_tokens: Number of input/prompt tokens.
            completion_tokens: Number of output/completion tokens.
            model: Model name for pricing lookup. Falls back to the default
                model if *None*.

        Returns:
            Estimated cost in USD.
        """
        ...


# ---------------------------------------------------------------------------
# OpenAI-compatible HTTP implementation
# ---------------------------------------------------------------------------


class OpenAICompatibleProvider(LLMProvider):
    """Generic provider for any OpenAI-compatible API endpoint.

    Subclasses should override the :attr:`PRICING` class variable and
    typically provide convenient constructors with preset defaults.
    """

    #: Pricing table: ``{model_name: {"input": $/Mtok, "output": $/Mtok}}``.
    PRICING: ClassVar[dict[str, dict[str, float]]] = {}

    #: Lowercase provider name used in logs and repr.
    PROVIDER_NAME: ClassVar[str] = "generic"

    #: Default base URL for the API endpoint.
    BASE_URL: ClassVar[str] = ""

    #: Default model name when none is specified.
    DEFAULT_MODEL: ClassVar[str] = ""

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        default_model: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        """Initialize the provider.

        Args:
            api_key: API key for authentication.
            base_url: Base URL of the API endpoint. Uses :attr:`BASE_URL` if
                *None*.
            default_model: Default model name. Uses :attr:`DEFAULT_MODEL` if
                *None*.
            timeout: Request timeout in seconds.
        """
        self._api_key = api_key
        self._base_url = (base_url or self.BASE_URL).rstrip("/")
        self._default_model = default_model or self.DEFAULT_MODEL
        self._timeout = timeout
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        """Lazily create and return the :class:`httpx.Client` with auth headers."""
        if self._client is None:
            self._client = httpx.Client(
                timeout=httpx.Timeout(self._timeout),
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    def _build_payload(
        self,
        messages: list[dict[str, str]],
        model: str | None,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Assemble the JSON payload for the chat completion request.

        Args:
            messages: Chat message list.
            model: Model name (uses default if *None*).
            temperature: Sampling temperature.
            max_tokens: Max output tokens.
            **kwargs: Additional API parameters.

        Returns:
            JSON-serializable payload dict.
        """
        payload: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        payload.update(kwargs)
        return payload

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send a chat completion request to an OpenAI-compatible endpoint.

        Args:
            messages: List of message dicts with ``role`` and ``content`` keys.
            model: Model name to use. Uses the provider default if *None*.
            temperature: Sampling temperature (0.0 to 2.0).
            max_tokens: Maximum tokens in the response.
            **kwargs: Additional parameters passed to the API.

        Returns:
            LLMResponse with content and usage statistics.

        Raises:
            httpx.HTTPError: On non-2xx HTTP responses.
            httpx.TimeoutException: When the request exceeds the timeout.
        """
        payload = self._build_payload(
            messages, model, temperature, max_tokens, **kwargs
        )
        url = f"{self._base_url}/chat/completions"
        logger.info("Calling %s with model=%s", url, payload["model"])

        response = self.client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

        choice = data["choices"][0]
        content = choice["message"]["content"]
        usage_data = data.get("usage", {})
        usage = Usage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )

        logger.info(
            "Response: %d tokens (prompt=%d completion=%d)",
            usage.total_tokens,
            usage.prompt_tokens,
            usage.completion_tokens,
        )

        return LLMResponse(content=content, usage=usage)

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count using a character-based heuristic.

        For Chinese text, roughly 1 character ≈ 1.5–2 tokens.
        For English / other scripts, roughly 1 token ≈ 4 characters.
        This is a rough estimate; use ``tiktoken`` for accurate counts.

        Args:
            text: Input text string.

        Returns:
            Estimated token count.
        """
        if not text:
            return 0
        chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        non_chinese = len(text) - chinese_chars
        return int(chinese_chars * 1.8 + non_chinese / 4.0)

    def calculate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str | None = None,
    ) -> float:
        """Calculate USD cost based on :attr:`PRICING`.

        Args:
            prompt_tokens: Number of input/prompt tokens.
            completion_tokens: Number of output/completion tokens.
            model: Model name for pricing lookup. Falls back to the default
                model if *None*.

        Returns:
            Estimated cost in USD. Returns 0.0 if no pricing data is found.
        """
        model = model or self._default_model
        model_pricing = self.PRICING.get(model)

        if model_pricing is None:
            logger.warning(
                "No pricing found for model=%s in provider=%s",
                model,
                self.PROVIDER_NAME,
            )
            return 0.0

        input_cost = (prompt_tokens / 1_000_000) * model_pricing["input"]
        output_cost = (completion_tokens / 1_000_000) * model_pricing["output"]
        return input_cost + output_cost

    def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> OpenAICompatibleProvider:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"base_url={self._base_url!r}, "
            f"default_model={self._default_model!r})"
        )
