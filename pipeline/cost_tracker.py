"""LLM API call cost tracking with CNY pricing for domestic & international models.

Provides :class:`CostTracker` for accumulating token usage across providers
and calculating estimated cost.  A global :data:`cost_tracker` instance is
available for use throughout the pipeline.

This module has zero dependencies on the rest of the pipeline to avoid
circular imports.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["CostTracker", "cost_tracker"]


# ---------------------------------------------------------------------------
# Internal lightweight token counter (avoids circular import from llm_provider)
# ---------------------------------------------------------------------------


@dataclass
class _TokenCount:
    """Internal accumulator with the same shape as ``llm_provider.Usage``."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


# ---------------------------------------------------------------------------
# CostTracker
# ---------------------------------------------------------------------------


class CostTracker:
    """Track token usage and estimated cost across LLM API calls.

    Accumulates token usage per provider and calculates estimated cost
    in CNY (元) based on configurable pricing tables.

    The :meth:`record` method accepts any object with ``prompt_tokens``,
    ``completion_tokens``, and ``total_tokens`` integer attributes
    (e.g. :class:`pipeline.llm_provider.Usage`).

    Example::

        tracker = CostTracker()
        tracker.record(usage, "deepseek")
        print(f"Cost: ¥{tracker.estimated_cost('deepseek'):.4f}")
        tracker.report()
    """

    PRICING_CNY: dict[str, dict[str, float]] = {
        "deepseek": {"input": 3, "output": 6},
        "qwen": {"input": 4, "output": 12},
        "openai": {"input": 150, "output": 600},
    }
    """Pricing in CNY (元) per million tokens per provider."""

    def __init__(self) -> None:
        """Initialize an empty CostTracker."""
        self._records: dict[str, _TokenCount] = {}

    def record(self, usage: Any, provider: str) -> None:
        """Record token usage from a single API call.

        Args:
            usage: An object with ``prompt_tokens``, ``completion_tokens``,
                and ``total_tokens`` integer attributes (e.g.
                :class:`~pipeline.llm_provider.Usage`).
            provider: Lowercase provider name (e.g. ``deepseek``, ``qwen``,
                ``openai``).
        """
        if provider not in self._records:
            self._records[provider] = _TokenCount()
        rec = self._records[provider]
        rec.prompt_tokens += getattr(usage, "prompt_tokens", 0)
        rec.completion_tokens += getattr(usage, "completion_tokens", 0)
        rec.total_tokens += getattr(usage, "total_tokens", 0)

    def estimated_cost(self, provider: str) -> float:
        """Calculate total estimated cost in CNY for a provider.

        Args:
            provider: Lowercase provider name.

        Returns:
            Estimated total cost in CNY (元). Returns 0.0 if no pricing
            data or no records exist for the provider.
        """
        rec = self._records.get(provider)
        if rec is None:
            return 0.0
        pricing = self.PRICING_CNY.get(provider)
        if pricing is None:
            logger.warning(
                "No CNY pricing data for provider=%s", provider
            )
            return 0.0
        input_cost = (rec.prompt_tokens / 1_000_000) * pricing["input"]
        output_cost = (rec.completion_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost

    def report(self, provider: str | None = None) -> None:
        """Print a human-readable cost report.

        Args:
            provider: If given, report only for that provider. If *None*,
                report for all recorded providers.
        """
        if not self._records:
            logger.info("CostTracker: No records yet.")
            return

        providers = (
            [provider] if provider else sorted(self._records.keys())
        )
        total_cost = 0.0

        header = (
            f"{'Provider':<12} {'Prompt Tokens':>14} "
            f"{'Comp Tokens':>14} {'Total Tokens':>14} "
            f"{'Cost (¥)':>12}"
        )
        sep = "-" * len(header)

        lines = [sep, header, sep]
        for prov in providers:
            rec = self._records.get(prov)
            if rec is None:
                continue
            cost = self.estimated_cost(prov)
            total_cost += cost
            lines.append(
                f"{prov:<12} {rec.prompt_tokens:>14,} "
                f"{rec.completion_tokens:>14,} {rec.total_tokens:>14,} "
                f"{cost:>12.4f}"
            )
        lines.append(sep)
        lines.append(
            f"{'TOTAL':<12} {'':>14} {'':>14} {'':>14} {total_cost:>12.4f}"
        )
        lines.append(sep)

        for line in lines:
            logger.info(line)


# Global tracker instance for use across the pipeline.
cost_tracker = CostTracker()
