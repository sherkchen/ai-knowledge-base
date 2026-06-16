"""
Router pattern: two-layer intent classification with keyword fast-path
and LLM fallback.

Intent types:
    - github_search: search GitHub repositories via GitHub Search API
    - knowledge_query: search local knowledge base index
    - general_chat: answer directly with LLM
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
from abc import ABC, abstractmethod
from typing import Callable

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.model_client import chat


# ---------------------------------------------------------------------------
# Intent constants
# ---------------------------------------------------------------------------

INTENT_GITHUB = "github_search"
INTENT_KNOWLEDGE = "knowledge_query"
INTENT_CHAT = "general_chat"


# ============================================================================
# Layer 1: Classifier abstraction
# ============================================================================

class BaseClassifier(ABC):
    """Abstract classifier: given a query, returns an intent string or None."""

    @abstractmethod
    def classify(self, query: str) -> str | None:
        ...


class KeywordClassifier(BaseClassifier):
    """Keyword-based fast-path classifier (zero cost, no LLM)."""

    def __init__(self, keyword_map: dict[str, str] | None = None) -> None:
        self._keyword_map = keyword_map or self._default_keyword_map()

    @staticmethod
    def _default_keyword_map() -> dict[str, str]:
        return {
            INTENT_GITHUB: [
                "github", "repo", "repository", "star", "fork", "pull request",
                "issue", "开源", "仓库", "git clone", "gh ",
            ],
            INTENT_KNOWLEDGE: [
                "知识库", "知识", "文章", "检索", "查找", "论文", "研究",
                "knowledge", "article", "paper", "research",
            ],
        }

    def classify(self, query: str) -> str | None:
        ql = query.lower()
        for intent, keywords in self._keyword_map.items():
            if any(kw in ql for kw in keywords):
                return intent
        return None


class LLMClassifier(BaseClassifier):
    """LLM-based classification fallback for ambiguous queries."""

    CLASSIFY_SYSTEM_PROMPT = """\
You are an intent classifier. Analyze the user's query and classify it into exactly one of these three categories:

- github_search: The user wants to search for GitHub repositories, open-source projects, or code on GitHub.
- knowledge_query: The user wants to search an internal knowledge base for articles, papers, research, or curated technical content.
- general_chat: General conversation, questions, coding help, or anything else.

Reply with ONLY one word: github_search, knowledge_query, or general_chat."""

    def __init__(
        self,
        valid_intents: tuple[str, ...] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 16,
    ) -> None:
        self._valid_intents = valid_intents or (INTENT_GITHUB, INTENT_KNOWLEDGE, INTENT_CHAT)
        self._temperature = temperature
        self._max_tokens = max_tokens

    def classify(self, query: str) -> str | None:
        result = chat(
            prompt=f"User query: {query}",
            system_prompt=self.CLASSIFY_SYSTEM_PROMPT,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        label = result["content"].strip().lower()
        for intent in self._valid_intents:
            if intent in label:
                return intent
        return None


class ClassifierPipeline(BaseClassifier):
    """Chain multiple classifiers; stops at the first non-None result."""

    def __init__(self, classifiers: list[BaseClassifier]) -> None:
        self._classifiers = classifiers

    def classify(self, query: str) -> str | None:
        for classifier in self._classifiers:
            intent = classifier.classify(query)
            if intent is not None:
                return intent
        return None


# ============================================================================
# Layer 2: Intent handler abstraction
# ============================================================================

class BaseIntentHandler(ABC):
    """Handler for a specific intent."""

    @property
    @abstractmethod
    def intent(self) -> str:
        ...

    @abstractmethod
    def handle(self, query: str) -> str:
        ...


class IntentHandler(BaseIntentHandler):
    """Convenience handler that wraps an intent name and a callable."""

    def __init__(self, intent: str, handler: Callable[[str], str]) -> None:
        self._intent = intent
        self._handler = handler

    @property
    def intent(self) -> str:
        return self._intent

    def handle(self, query: str) -> str:
        return self._handler(query)


# ============================================================================
# Existing handler implementations (refactored as free functions)
# ============================================================================

GITHUB_API = "https://api.github.com/search/repositories"


def handle_github_search(query: str) -> str:
    encoded = urllib.parse.quote(query)
    url = f"{GITHUB_API}?q={encoded}&per_page=5"
    try:
        resp = httpx.get(
            url,
            headers={"User-Agent": "ai-knowledge-base/1.0"},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        return f"GitHub API error: {e.response.status_code}"
    except Exception as e:
        return f"GitHub search failed: {e}"

    items = data.get("items", [])
    if not items:
        return "No GitHub repositories found for this query."

    lines = [f"Found {data.get('total_count', 0)} repositories (showing top {len(items)}):"]
    for item in items:
        name = item.get("full_name", "unknown")
        desc = item.get("description") or "(no description)"
        stars = item.get("stargazers_count", 0)
        html_url = item.get("html_url", "")
        lines.append(f"  {name} ★{stars}\n  {desc}\n  {html_url}")
    return "\n".join(lines)


def handle_knowledge_query(query: str) -> str:
    index_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "knowledge", "articles", "index.json",
    )
    try:
        with open(index_path, encoding="utf-8") as f:
            index = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return f"Knowledge base unavailable: {e}"

    items = index.get("items", [])
    if not items:
        return "Knowledge base is empty."

    q_words = set(query.lower().split())
    scored = []
    for item in items:
        title_lower = item["title"].lower()
        score = sum(1 for w in q_words if w in title_lower)
        if score > 0:
            scored.append((score, item))

    if not scored:
        return "No matching articles found in knowledge base."

    scored.sort(key=lambda x: (-x[0], -x[1].get("relevance_score", 0)))
    top = scored[:5]

    lines = [f"Found {len(scored)} matching article(s) (showing top {len(top)}):"]
    for count, item in top:
        lines.append(
            f"  [{item['category']}] {item['title']} "
            f"(relevance: {item['relevance_score']}, id: {item['id']})"
        )
    return "\n".join(lines)


def handle_general_chat(query: str) -> str:
    result = chat(prompt=query)
    return result["content"]


# ============================================================================
# chat_json helper (wraps chat() with JSON output parsing)
# ============================================================================

def _chat_json(
    prompt: str,
    system_prompt: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> dict | list:
    json_system = (system_prompt or "") + "\nRespond with valid JSON only, no markdown fences."
    result = chat(
        prompt=prompt,
        system_prompt=json_system,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    content = result["content"].strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:]) if lines[-1].startswith("```") else "\n".join(lines[1:-1])
    return json.loads(content)


# ============================================================================
# Router: unified entry point with extensible architecture
# ============================================================================

class Router:
    """Intent-based query router.

    Extensibility points:
        - register_handler(): add or override intent handlers at runtime
        - classifier: swap or compose classification strategies
        - default_handler: customize the fallback behaviour

    Usage::

        router = Router()                       # defaults with keyword+LLM pipeline
        router.register_handler(MyHandler())    # add custom intent support
        router.register_handler(                 # override an existing handler
            IntentHandler("github_search", my_custom_github_handler)
        )
        answer = router.route(query)
    """

    def __init__(
        self,
        classifier: BaseClassifier | None = None,
        default_handler: Callable[[str], str] | None = None,
    ) -> None:
        self._classifier = classifier or ClassifierPipeline([
            KeywordClassifier(),
            LLMClassifier(),
        ])
        self._default_handler = default_handler or handle_general_chat
        self._handlers: dict[str, BaseIntentHandler] = {}

    # ---- handler registry ----

    def register_handler(self, handler: BaseIntentHandler) -> None:
        """Register (or override) a handler for its declared intent."""
        self._handlers[handler.intent] = handler

    def register_builtin_handlers(self) -> None:
        """Register the three default handlers bundled with this module."""
        self.register_handler(IntentHandler(INTENT_GITHUB, handle_github_search))
        self.register_handler(IntentHandler(INTENT_KNOWLEDGE, handle_knowledge_query))
        # general_chat is the default; no need to register it explicitly,
        # but we do so for symmetry / custom override support.
        self.register_handler(IntentHandler(INTENT_CHAT, handle_general_chat))

    # ---- routing ----

    def route(self, query: str) -> str:
        intent = self._classifier.classify(query)
        if intent is not None and intent in self._handlers:
            return self._handlers[intent].handle(query)
        return self._default_handler(query)


# ============================================================================
# Default instance —  backwards-compatible with the old route() function
# ============================================================================

_default_router = Router()
_default_router.register_builtin_handlers()
route = _default_router.route


# ============================================================================
# Self-test
# ============================================================================

if __name__ == "__main__":
    test_queries = [
        "how to use Python decorators?",
        "search for machine learning repos on GitHub",
        "查找关于 LLM agent 的知识库文章",
        "tell me a joke",
        "find llama.cpp on github",
    ]

    for q in test_queries:
        print(f"\n{'=' * 60}")
        print(f"Query: {q}")

        kw_intent = _default_router._classifier.classify(q)
        if kw_intent:
            intent = kw_intent
            print(f"Intent (classifier): {intent}")
        else:
            print("Intent: general_chat (no classifier match)")

        try:
            response = _default_router.route(q)
            print(f"Response:\n{response[:800]}")
        except Exception as e:
            print(f"Handler error: {e}")
