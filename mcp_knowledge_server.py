#!/usr/bin/env python3
"""MCP server that exposes local knowledge base for AI tools.

Implements JSON-RPC 2.0 over stdio with three tools:
  - search_articles: keyword search in titles and summaries
  - get_article: fetch full article by ID
  - knowledge_stats: summary statistics

Usage::

    python mcp_knowledge_server.py
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Knowledge loader
# ---------------------------------------------------------------------------

_ARTICLES_DIR = Path(__file__).resolve().parent / "knowledge" / "articles"


class KnowledgeBase:
    """In-memory index of all articles loaded from disk."""

    def __init__(self) -> None:
        self._articles: list[dict[str, Any]] = []
        self._by_id: dict[str, dict[str, Any]] = {}
        self._loaded = False

    def load(self) -> None:
        """Scan knowledge/articles/ subdirectories and load all JSON files."""
        if self._loaded:
            return

        articles: list[dict[str, Any]] = []
        seen: set[str] = set()

        for root, _dirs, files in os.walk(_ARTICLES_DIR):
            for fname in sorted(files):
                if not fname.endswith(".json"):
                    continue
                filepath = Path(root) / fname
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        article = json.load(f)
                except (json.JSONDecodeError, OSError):
                    continue  # skip corrupt files silently

                if not isinstance(article, dict):
                    continue

                aid = article.get("id", "")
                if not aid:
                    continue
                if aid in seen:
                    continue
                seen.add(aid)
                articles.append(article)

        self._articles = articles
        self._by_id = {a["id"]: a for a in articles if a.get("id")}
        self._loaded = True

    @property
    def articles(self) -> list[dict[str, Any]]:
        if not self._loaded:
            self.load()
        return self._articles

    def get_by_id(self, article_id: str) -> dict[str, Any] | None:
        if not self._loaded:
            self.load()
        return self._by_id.get(article_id)


_kb = KnowledgeBase()


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def _tool_search_articles(arguments: dict[str, Any]) -> dict[str, Any]:
    keyword = arguments.get("keyword", "")
    limit = max(1, min(50, int(arguments.get("limit", 5))))

    if not keyword:
        return {
            "content": [{"type": "text", "text": "Error: keyword is required"}],
            "isError": True,
        }

    kw = keyword.lower()
    scored: list[tuple[int, dict[str, Any]]] = []

    for article in _kb.articles:
        title = str(article.get("title", "")).lower()
        summary = str(article.get("summary", "")).lower()
        tags = " ".join(article.get("tags") or []).lower()

        score = 0
        if kw in title:
            score += 10
        if kw in tags:
            score += 5
        if kw in summary:
            score += 3

        if score == 0:
            continue

        scored.append((score, article))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = scored[:limit]

    items = []
    for score, article in results:
        items.append({
            "id": article.get("id"),
            "title": article.get("title"),
            "source": article.get("source"),
            "summary": article.get("summary"),
            "tags": article.get("tags"),
            "relevance_score": article.get("relevance_score"),
            "category": article.get("category"),
            "match_score": score,
        })

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps({
                    "keyword": keyword,
                    "total_matches": len(items),
                    "results": items,
                }, ensure_ascii=False, indent=2),
            }
        ],
    }


def _tool_get_article(arguments: dict[str, Any]) -> dict[str, Any]:
    article_id = arguments.get("article_id", "")

    if not article_id:
        return {
            "content": [{"type": "text", "text": "Error: article_id is required"}],
            "isError": True,
        }

    article = _kb.get_by_id(article_id)
    if article is None:
        return {
            "content": [
                {"type": "text", "text": f"Article not found: {article_id}"}
            ],
            "isError": True,
        }

    return {
        "content": [
            {"type": "text", "text": json.dumps(article, ensure_ascii=False, indent=2)},
        ],
    }


def _tool_knowledge_stats(_arguments: dict[str, Any]) -> dict[str, Any]:
    articles = _kb.articles
    total = len(articles)

    if total == 0:
        return {
            "content": [
                {"type": "text", "text": json.dumps({
                    "total_articles": 0,
                    "message": "No articles found in knowledge base.",
                }, indent=2)},
            ],
        }

    source_counter: Counter[str] = Counter()
    category_counter: Counter[str] = Counter()
    tag_counter: Counter[str] = Counter()
    scores: list[int] = []

    for a in articles:
        src = str(a.get("source", "unknown"))
        source_counter[src] += 1

        cat = str(a.get("category", "other"))
        category_counter[cat] += 1

        for tag in a.get("tags") or []:
            tag_counter[str(tag)] += 1

        score = a.get("relevance_score")
        if isinstance(score, (int, float)):
            scores.append(int(score))

    avg_score = round(sum(scores) / len(scores), 1) if scores else 0
    score_dist: dict[str, int] = {}
    for s in scores:
        bucket = str(s)
        score_dist[bucket] = score_dist.get(bucket, 0) + 1

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps({
                    "total_articles": total,
                    "average_relevance_score": avg_score,
                    "score_distribution": score_dist,
                    "by_source": dict(source_counter.most_common()),
                    "by_category": dict(category_counter.most_common()),
                    "top_tags": tag_counter.most_common(20),
                }, ensure_ascii=False, indent=2),
            },
        ],
    }


_TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "search_articles": {
        "handler": _tool_search_articles,
        "description": "Search knowledge articles by keyword in title, summary, and tags. Results ranked by match relevance.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "Search keyword (required).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 5).",
                },
            },
            "required": ["keyword"],
        },
    },
    "get_article": {
        "handler": _tool_get_article,
        "description": "Retrieve full article content by its unique ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "article_id": {
                    "type": "string",
                    "description": "Article ID, e.g. github-20260530-001.",
                },
            },
            "required": ["article_id"],
        },
    },
    "knowledge_stats": {
        "handler": _tool_knowledge_stats,
        "description": "Get knowledge base statistics: total articles, source distribution, top tags, and score distribution.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}

# ---------------------------------------------------------------------------
# JSON-RPC 2.0 helpers
# ---------------------------------------------------------------------------

_SERVER_NAME = "knowledge-base-mcp"
_SERVER_VERSION = "1.0.0"
_PROTOCOL_VERSION = "2024-11-05"

JSONRPC = "2.0"

ERROR_PARSE = (-32700, "Parse error")
ERROR_INVALID_REQUEST = (-32600, "Invalid Request")
ERROR_METHOD_NOT_FOUND = (-32601, "Method not found")
ERROR_INVALID_PARAMS = (-32602, "Invalid params")
ERROR_INTERNAL = (-32603, "Internal error")


def _make_response(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC, "id": req_id, "result": result}


def _make_error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": JSONRPC,
        "id": req_id,
        "error": {"code": code, "message": message},
    }


def _send(data: dict[str, Any]) -> None:
    """Write a JSON-RPC message to stdout, one line."""
    sys.stdout.write(json.dumps(data, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _read_message() -> dict[str, Any] | None:
    """Read one JSON-RPC message line from stdin."""
    line = sys.stdin.readline()
    if not line:
        return None
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# MCP request dispatcher
# ---------------------------------------------------------------------------


def _handle_initialize(req_id: Any, _params: Any) -> dict[str, Any]:
    _kb.load()  # eager-load on first handshake
    return _make_response(req_id, {
        "protocolVersion": _PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": _SERVER_NAME, "version": _SERVER_VERSION},
    })


def _handle_tools_list(req_id: Any, _params: Any) -> dict[str, Any]:
    tools = []
    for name, meta in sorted(_TOOL_REGISTRY.items()):
        tools.append({
            "name": name,
            "description": meta["description"],
            "inputSchema": meta["inputSchema"],
        })
    return _make_response(req_id, {"tools": tools})


def _handle_tools_call(req_id: Any, params: Any) -> dict[str, Any]:
    if not isinstance(params, dict):
        return _make_error(req_id, *ERROR_INVALID_PARAMS)

    tool_name = params.get("name", "")
    tool_args = params.get("arguments", {})

    if not isinstance(tool_args, dict):
        return _make_error(req_id, *ERROR_INVALID_PARAMS)

    meta = _TOOL_REGISTRY.get(tool_name)
    if meta is None:
        return _make_error(req_id, *ERROR_METHOD_NOT_FOUND)

    handler = meta["handler"]
    try:
        tool_result = handler(tool_args)
        return _make_response(req_id, tool_result)
    except Exception:
        return _make_error(req_id, *ERROR_INTERNAL)


_METHOD_HANDLERS: dict[str, Any] = {
    "initialize": _handle_initialize,
    "tools/list": _handle_tools_list,
    "tools/call": _handle_tools_call,
}


def dispatch(request: dict[str, Any]) -> dict[str, Any] | None:
    """Route a JSON-RPC request to the appropriate handler.

    Returns None for notifications (no response needed).
    """
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    # Notifications → no response
    if req_id is None:
        if method == "notifications/initialized":
            return None
        return None  # silently ignore unknown notifications

    handler = _METHOD_HANDLERS.get(method)
    if handler is None:
        return _make_error(req_id, *ERROR_METHOD_NOT_FOUND)

    try:
        return handler(req_id, params)
    except Exception:
        return _make_error(req_id, *ERROR_INTERNAL)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def main() -> int:
    """Run the MCP server main loop on stdio."""
    # Preload knowledge base
    _kb.load()

    # Log server start to stderr (stdout is reserved for JSON-RPC)
    print(
        f"MCP server '{_SERVER_NAME}' v{_SERVER_VERSION} started. "
        f"Loaded {len(_kb.articles)} articles.",
        file=sys.stderr,
    )

    while True:
        request = _read_message()
        if request is None:
            break  # stdin closed

        response = dispatch(request)
        if response is not None:
            _send(response)


if __name__ == "__main__":
    main()
