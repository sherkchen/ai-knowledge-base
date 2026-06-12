"""OpenAI provider implementation."""

from __future__ import annotations

import os
from typing import ClassVar

from pipeline.llm_provider import OpenAICompatibleProvider


class OpenAIProvider(OpenAICompatibleProvider):
    """Provider for the official OpenAI API.

    Uses ``OPENAI_API_KEY`` environment variable if no *api_key* is provided.

    Example::

        provider = OpenAIProvider()
        response = provider.chat([{"role": "user", "content": "Hello"}])
    """

    PROVIDER_NAME: ClassVar[str] = "openai"
    BASE_URL: ClassVar[str] = "https://api.openai.com/v1"
    DEFAULT_MODEL: ClassVar[str] = "gpt-4o-mini"

    PRICING: ClassVar[dict[str, dict[str, float]]] = {
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4.1": {"input": 2.00, "output": 8.00},
        "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
        "gpt-4.1-nano": {"input": 0.10, "output": 0.40},
        "o3": {"input": 10.00, "output": 40.00},
        "o4-mini": {"input": 1.10, "output": 4.40},
    }

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        """Initialize the OpenAI provider.

        Args:
            api_key: API key. Reads ``OPENAI_API_KEY`` from the environment
                if *None*.
            base_url: Override the default OpenAI base URL.
            default_model: Override the default model (``gpt-4o-mini``).
            timeout: Request timeout in seconds.

        Raises:
            ValueError: If no API key is provided or found in the environment.
        """
        api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError(
                "No API key provided. Set OPENAI_API_KEY in the environment."
            )
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            default_model=default_model,
            timeout=timeout,
        )
