"""Unified LLM calling client supporting DeepSeek, Qwen, and OpenAI providers.

Provides a consistent interface for chat completion with built-in retry,
token estimation, cost calculation, and convenient one-liner usage.

Usage::

    from pipeline.model_client import quick_chat

    answer = quick_chat("What is RAG?", system_prompt="Reply in Chinese.")
"""

from __future__ import annotations

import logging
import os
import random
import time
from typing import Any

import httpx

from pipeline.deepseek_model import DeepSeekProvider
from pipeline.llm_provider import LLMProvider, LLMResponse, OpenAICompatibleProvider
from pipeline.openai_model import OpenAIProvider
from pipeline.qwen_model import QwenProvider

logger = logging.getLogger(__name__)

__all__ = [
    "LLMProvider",
    "LLMResponse",
    "OpenAICompatibleProvider",
    "OpenAIProvider",
    "DeepSeekProvider",
    "QwenProvider",
    "chat_with_retry",
    "quick_chat",
    "get_provider",
    "reset_default_provider",
]


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

_PROVIDER_CLASSES: dict[str, type[OpenAICompatibleProvider]] = {
    "deepseek": DeepSeekProvider,
    "openai": OpenAIProvider,
    "qwen": QwenProvider,
}


# ---------------------------------------------------------------------------
# Global cached default provider
# ---------------------------------------------------------------------------

_default_provider: OpenAICompatibleProvider | None = None


def get_provider(provider_name: str | None = None) -> LLMProvider:
    """Create or return a cached provider instance.

    Reads ``LLM_PROVIDER`` from the environment if *provider_name* is not
    given.  Each provider subclass looks up its own API key from the
    corresponding environment variable (e.g. ``DEEPSEEK_API_KEY``).

    Args:
        provider_name: One of ``deepseek``, ``openai``, ``qwen``.
            Defaults to ``LLM_PROVIDER`` env var, then ``deepseek``.

    Returns:
        A configured :class:`LLMProvider` instance.

    Raises:
        ValueError: If the provider name is unknown.
    """
    global _default_provider

    if provider_name is None:
        provider_name = os.getenv("LLM_PROVIDER", "deepseek").lower()
        print("provider_name ", provider_name)

    if _default_provider is not None:
        return _default_provider

    provider_cls = _PROVIDER_CLASSES.get(provider_name)
    if provider_cls is None:
        supported = ", ".join(sorted(_PROVIDER_CLASSES.keys()))
        raise ValueError(
            f"Unknown LLM_PROVIDER '{provider_name}'. Supported: {supported}"
        )

    _default_provider = provider_cls()
    return _default_provider


def reset_default_provider() -> None:
    """Reset the cached default provider (useful for testing)."""
    global _default_provider
    if _default_provider is not None:
        _default_provider.close()
        _default_provider = None


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------


def chat_with_retry(
    provider: LLMProvider,
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    max_retries: int = 3,
    base_delay: float = 1.0,
    **kwargs: Any,
) -> LLMResponse:
    """Call chat with exponential backoff retry on failure.

    Args:
        provider: The LLM provider instance to use.
        messages: List of message dicts with ``role`` and ``content`` keys.
        model: Model name to use. Uses the provider default if *None*.
        temperature: Sampling temperature (0.0 to 2.0).
        max_tokens: Maximum tokens in the response.
        max_retries: Maximum number of retry attempts (default 3).
        base_delay: Base delay in seconds for exponential backoff.
        **kwargs: Additional parameters passed to the API.

    Returns:
        LLMResponse with content and usage statistics.

    Raises:
        RuntimeError: If all retry attempts are exhausted.
    """
    last_exception: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return provider.chat(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            last_exception = exc
            if attempt < max_retries:
                delay = base_delay * (2**attempt) + random.uniform(0, 0.5)
                logger.warning(
                    "Attempt %d/%d failed: %s. Retrying in %.1fs...",
                    attempt + 1,
                    max_retries + 1,
                    exc,
                    delay,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "All %d attempts exhausted. Last error: %s",
                    max_retries + 1,
                    exc,
                )

    raise RuntimeError(
        f"Chat request failed after {max_retries + 1} attempts"
    ) from last_exception


# ---------------------------------------------------------------------------
# Convenience: quick one-liner
# ---------------------------------------------------------------------------


def quick_chat(
    prompt: str,
    system_prompt: str | None = None,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> str:
    """Convenience function: one-liner to call the default LLM.

    Creates a chat session using the provider configured via ``LLM_PROVIDER``
    and returns only the text content.

    Args:
        prompt: User message content.
        system_prompt: Optional system message to set context.
        model: Model name override. Uses the provider default if *None*.
        temperature: Sampling temperature (0.0 to 2.0).
        max_tokens: Maximum tokens in the response.

    Returns:
        The response content string from the LLM.

    Example::

        >>> answer = quick_chat("什么是 RAG?", system_prompt="用中文回答")
    """
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    provider = get_provider()
    response = chat_with_retry(
        provider,
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.content


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    sep = "=" * 60

    # --- Test 1: Direct instantiation of each provider ---
    print(f"\n{sep}")
    print("Test 1: Direct provider instantiation")

    provider_classes: list[type[OpenAICompatibleProvider]] = [
        DeepSeekProvider,
        OpenAIProvider,
        QwenProvider,
    ]
    for cls in provider_classes:
        try:
            inst = cls()
            print(f"  {cls.__name__}: {inst}")
            inst.close()
            print(f"  ✓ {cls.__name__} OK")
        except ValueError as exc:
            print(f"  ⚠ {cls.__name__} skipped: {exc}")

    # --- Test 2: Token estimation ---
    print(f"\n{sep}")
    print("Test 2: Token estimation")

    # Use a provider that doesn't need a real API key for offline tests.
    dummy = OpenAICompatibleProvider(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
    )

    test_texts: list[tuple[str, str]] = [
        (
            "English only",
            "Hello, world! This is a test sentence for token estimation.",
        ),
        (
            "Chinese only",
            "你好，世界！这是一个用于token估算的测试句子。",
        ),
        ("Mixed CN/EN", "Hello你好world世界 testing测试"),
        ("Empty", ""),
    ]
    for label, text in test_texts:
        est = dummy.estimate_tokens(text)
        print(f"  {label}: {len(text)} chars, ~{est} tokens")

    dummy.close()

    # --- Test 3: Cost calculation per provider ---
    print(f"\n{sep}")
    print("Test 3: Cost calculation")

    cost_cases: list[tuple[type[OpenAICompatibleProvider], str, int, int]] = [
        (DeepSeekProvider, "deepseek-chat", 1_000, 500),
        (DeepSeekProvider, "deepseek-reasoner", 2_000, 800),
        (OpenAIProvider, "gpt-4o", 1_000, 500),
        (OpenAIProvider, "gpt-4o-mini", 5_000, 2_000),
        (QwenProvider, "qwen-plus", 1_000, 300),
        (QwenProvider, "qwen-max", 1_000, 300),
        (QwenProvider, "qwen-turbo", 10_000, 5_000),
        (DeepSeekProvider, "unknown-model", 1_000, 500),
    ]
    for cls, model, prompt_tok, comp_tok in cost_cases:
        # Instantiate with a fake key for offline cost calc.
        inst = cls(api_key="sk-test")
        cost = inst.calculate_cost(prompt_tok, comp_tok, model=model)
        print(
            f"  {cls.PROVIDER_NAME}/{model}: "
            f"{prompt_tok}+{comp_tok} tokens → ${cost:.6f}"
        )
        inst.close()

    # --- Test 4: get_provider + quick_chat (requires real API key) ---
    print(f"\n{sep}")
    print("Test 4: get_provider() + quick_chat()")
    try:
        prov = get_provider()
        print(f"  Provider: {prov}")
        print(f"  ✓ get_provider OK")
    except ValueError as exc:
        print(f"  ⚠ get_provider skipped: {exc}")

    try:
        answer = quick_chat("Say 'hello' in exactly one word.", temperature=0)
        print(f"  quick_chat response: {answer}")
        print("  ✓ quick_chat OK")
    except ValueError as exc:
        print(f"  ⚠ quick_chat skipped: {exc}")
    except Exception as exc:
        print(f"  ✗ quick_chat failed: {exc}")

    # --- Test 5: chat_with_retry ---
    print(f"\n{sep}")
    print("Test 5: chat_with_retry with system prompt")
    try:
        prov = get_provider()
        resp = chat_with_retry(
            prov,
            messages=[
                {"role": "system", "content": "Reply in Chinese only."},
                {"role": "user", "content": "What is 1+1?"},
            ],
            temperature=0,
        )
        print(f"  Content: {resp.content}")
        print(f"  Usage:   {resp.usage}")
        cost = prov.calculate_cost(
            resp.usage.prompt_tokens, resp.usage.completion_tokens
        )
        print(f"  Cost:    ${cost:.6f}")
        print("  ✓ chat_with_retry OK")
    except ValueError as exc:
        print(f"  ⚠ Skipped: {exc}")
    except Exception as exc:
        print(f"  ✗ Failed: {exc}")

    # --- Cleanup ---
    print(f"\n{sep}")
    reset_default_provider()
    print("Done.")
