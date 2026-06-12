"""Qwen (Tongyi Qianwen / 通义千问) provider implementation."""

from __future__ import annotations

import os
from typing import ClassVar

from pipeline.llm_provider import OpenAICompatibleProvider


class QwenProvider(OpenAICompatibleProvider):
    """Provider for the Alibaba Qwen (DashScope) API.

    Uses ``QWEN_API_KEY`` environment variable if no *api_key* is provided.

    Example::

        provider = QwenProvider()
        response = provider.chat([{"role": "user", "content": "Hello"}])
    """

    PROVIDER_NAME: ClassVar[str] = "qwen"
    BASE_URL: ClassVar[str] = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    DEFAULT_MODEL: ClassVar[str] = "qwen-plus"

    PRICING: ClassVar[dict[str, dict[str, float]]] = {
        "qwen-turbo": {"input": 0.30, "output": 0.60},
        "qwen-plus": {"input": 0.80, "output": 2.00},
        "qwen-max": {"input": 2.40, "output": 9.60},
        "qwen-turbo-latest": {"input": 0.30, "output": 0.60},
        "qwen-plus-latest": {"input": 0.80, "output": 2.00},
        "qwen-max-latest": {"input": 2.40, "output": 9.60},
    }

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        """Initialize the Qwen provider.

        Args:
            api_key: API key. Reads ``QWEN_API_KEY`` from the environment
                if *None*.
            base_url: Override the default Qwen (DashScope) base URL.
            default_model: Override the default model (``qwen-plus``).
            timeout: Request timeout in seconds.

        Raises:
            ValueError: If no API key is provided or found in the environment.
        """
        api_key = api_key or os.getenv("QWEN_API_KEY", "")
        if not api_key:
            raise ValueError(
                "No API key provided. Set QWEN_API_KEY in the environment."
            )
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            default_model=default_model,
            timeout=timeout,
        )
