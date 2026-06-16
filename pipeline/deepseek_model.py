"""DeepSeek provider implementation."""

from __future__ import annotations

import os
from typing import ClassVar

from pipeline.llm_provider import OpenAICompatibleProvider


class DeepSeekProvider(OpenAICompatibleProvider):
    """Provider for the DeepSeek API.

    Uses ``DEEPSEEK_API_KEY`` environment variable if no *api_key* is provided.

    Example::

        provider = DeepSeekProvider()
        response = provider.chat([{"role": "user", "content": "Hello"}])
    """

    PROVIDER_NAME: ClassVar[str] = "deepseek"
    # BASE URL (OpenAI 格式) https://api.deepseek.com
    #BASE URL (Anthropic 格式)
    BASE_URL: ClassVar[str] = "https://api.deepseek.com"
    DEFAULT_MODEL: ClassVar[str] = "deepseek-v4-pro"

    PRICING: ClassVar[dict[str, dict[str, float]]] = {
        "deepseek-chat": {"input": 1, "output": 3},
        "deepseek-v4-pro": {"input": 2, "output": 6},
    }

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        """Initialize the DeepSeek provider.

        Args:
            api_key: API key. Reads ``DEEPSEEK_API_KEY`` from the environment
                if *None*.
            base_url: Override the default DeepSeek base URL.
            default_model: Override the default model (``deepseek-chat``).
            timeout: Request timeout in seconds.

        Raises:
            ValueError: If no API key is provided or found in the environment.
        """
        api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        if not api_key:
            raise ValueError(
                "No API key provided. Set DEEPSEEK_API_KEY in the environment."
            )
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            default_model=default_model,
            timeout=timeout,
        )
