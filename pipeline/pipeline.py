"""Four-step knowledge base automation pipeline.

Collect -> Analyze -> Organize -> Save

Usage::

    python -m pipeline.pipeline --sources github --limit 10
    python -m pipeline.pipeline --sources github,rss --limit 20 --dry-run
    python -m pipeline.pipeline --sources rss --limit 5 --verbose
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure the project root is on sys.path so that ``pipeline`` can be
# imported as a package regardless of how this script is invoked.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import httpx

from pipeline.model_client import chat_with_retry, get_provider
from pipeline.cost_tracker import cost_tracker

logger = logging.getLogger(__name__)

__all__ = ["run_pipeline", "collect_github", "collect_rss"]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RAW_DIR = _PROJECT_ROOT / "knowledge" / "raw"
ARTICLES_DIR = _PROJECT_ROOT / "knowledge" / "articles"
INDEX_FILE = ARTICLES_DIR / "index.json"

GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
GITHUB_SEARCH_QUERY = "ai+topic:llm"

DEFAULT_RSS_SOURCES: list[str] = [
    "https://hnrss.org/frontpage?q=ai+OR+llm+OR+agent",
    "https://arxiv.org/rss/cs.AI",
    "https://arxiv.org/rss/cs.CL",
]

_REQUIRED_FIELDS: set[str] = {
    "id", "title", "source", "source_url", "summary",
    "tags", "relevance_score", "status", "fetched_at",
}

_NONEMPTY_STRING_FIELDS: set[str] = {
    "id", "title", "source", "source_url", "status", "fetched_at",
}

_VALID_CATEGORIES: set[str] = {
    "tool", "framework", "library", "research", "news", "paper", "other",
}

# ---------------------------------------------------------------------------
# Step 1: Collect
# ---------------------------------------------------------------------------


def collect_github(limit: int = 10) -> list[dict[str, Any]]:
    """Fetch AI-related repositories from GitHub Search API.

    Args:
        limit: Maximum number of repositories to fetch.

    Returns:
        List of normalized item dicts.
    """
    params: dict[str, str | int] = {
        "q": GITHUB_SEARCH_QUERY,
        "sort": "stars",
        "order": "desc",
        "per_page": min(limit, 100),
    }

    logger.info("Fetching GitHub repositories (limit=%d)...", limit)

    with httpx.Client(timeout=30.0) as client:
        response = client.get(
            GITHUB_SEARCH_URL,
            params=params,
            headers={"Accept": "application/vnd.github.v3+json"},
        )
        response.raise_for_status()
        data = response.json()

    items: list[dict[str, Any]] = []
    for repo in data.get("items", []):
        items.append(_normalize_github_item(repo))

    logger.info("Collected %d GitHub repositories.", len(items))
    return items


def _normalize_github_item(repo: dict[str, Any]) -> dict[str, Any]:
    """Normalize a GitHub API repository object into a flat dict."""
    owner = repo.get("owner") or {}
    return {
        "title": repo.get("full_name", repo.get("name", "")),
        "source": "github",
        "source_url": repo.get("html_url", ""),
        "description": repo.get("description") or "",
        "topics": repo.get("topics") or [],
        "stars": repo.get("stargazers_count", 0),
        "language": repo.get("language"),
        "published_at": repo.get("created_at"),
        "author": owner.get("login") if owner else None,
    }


def collect_rss(limit: int = 10) -> list[dict[str, Any]]:
    """Fetch items from RSS/Atom feeds using simple regex parsing.

    Args:
        limit: Maximum number of items to collect across all feeds.

    Returns:
        List of normalized item dicts.
    """
    items: list[dict[str, Any]] = []

    with httpx.Client(timeout=30.0) as client:
        for feed_url in DEFAULT_RSS_SOURCES:
            if len(items) >= limit:
                break
            try:
                logger.info("Fetching RSS feed: %s", feed_url)
                response = client.get(feed_url, follow_redirects=True)
                response.raise_for_status()
                parsed = _parse_rss(response.text)
                for raw_item in parsed:
                    if len(items) >= limit:
                        break
                    items.append(_normalize_rss_item(raw_item))
            except Exception as exc:
                logger.warning(
                    "Failed to fetch/parse RSS feed %s: %s", feed_url, exc
                )
                continue

    logger.info("Collected %d RSS items.", len(items))
    return items


def _parse_rss(xml_text: str) -> list[dict[str, str]]:
    """Parse RSS 2.0 / Atom XML with regex.

    Supports both ``<item>`` (RSS) and ``<entry>`` (Atom) blocks.

    Args:
        xml_text: Raw XML string from RSS/Atom feed.

    Returns:
        List of item dicts with ``title``, ``link``, ``description``,
        ``pubDate``, and ``author`` keys.
    """
    items: list[dict[str, str]] = []

    item_pattern = re.compile(
        r"<(?:item|entry)\b[^>]*>.*?</(?:item|entry)>", re.DOTALL
    )
    title_pattern = re.compile(
        r"<(?:title)[^>]*>(.*?)</(?:title)>",
        re.DOTALL | re.IGNORECASE,
    )
    # Atom: <link href="..."/>
    atom_link_pattern = re.compile(
        r'<link[^>]*href="([^"]*)"[^>]*/?>',
        re.DOTALL | re.IGNORECASE,
    )
    # RSS: <link>...</link>
    rss_link_pattern = re.compile(
        r"<link\b[^>]*>(.*?)</link>",
        re.DOTALL | re.IGNORECASE,
    )
    desc_pattern = re.compile(
        r"<(?:description|summary|content)\b[^>]*>(.*?)"
        r"</(?:description|summary|content)>",
        re.DOTALL | re.IGNORECASE,
    )
    date_pattern = re.compile(
        r"<(?:pubDate|published|updated|dc:date)\b[^>]*>(.*?)"
        r"</(?:pubDate|published|updated|dc:date)>",
        re.DOTALL | re.IGNORECASE,
    )
    author_pattern = re.compile(
        r"<(?:author|dc:creator)\b[^>]*>(.*?)</(?:author|dc:creator)>",
        re.DOTALL | re.IGNORECASE,
    )

    for match in item_pattern.finditer(xml_text):
        block = match.group(0)

        title_match = title_pattern.search(block)
        desc_match = desc_pattern.search(block)

        link_match = atom_link_pattern.search(block)
        if not link_match:
            link_match = rss_link_pattern.search(block)

        date_match = date_pattern.search(block)
        author_match = author_pattern.search(block)

        items.append({
            "title": _clean_html(title_match.group(1) if title_match else ""),
            "link": link_match.group(1).strip() if link_match else "",
            "description": _clean_html(
                desc_match.group(1) if desc_match else ""
            ),
            "pubDate": date_match.group(1).strip() if date_match else "",
            "author": _clean_html(
                author_match.group(1) if author_match else ""
            ),
        })

    return items


def _normalize_rss_item(item: dict[str, str]) -> dict[str, Any]:
    """Normalize a parsed RSS item into a flat dict."""
    return {
        "title": item.get("title", ""),
        "source": "rss",
        "source_url": item.get("link", ""),
        "description": item.get("description", ""),
        "published_at": item.get("pubDate"),
        "author": item.get("author"),
    }


def _clean_html(text: str) -> str:
    """Strip HTML tags, CDATA sections, and decode common entities."""
    # Remove CDATA wrappers
    text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text, flags=re.DOTALL)
    # Remove HTML tags
    text = re.sub(r"<[^>]*>", "", text)
    # Decode common entities
    html_entities = {
        "&amp;": "&",
        "&lt;": "<",
        "&gt;": ">",
        "&quot;": '"',
        "&#39;": "'",
        "&apos;": "'",
        "&#x27;": "'",
        "&#x2F;": "/",
        "&#x60;": "`",
    }
    for entity, char in html_entities.items():
        text = text.replace(entity, char)
    # Decode numeric entities
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    text = re.sub(r"&#[xX]([0-9a-fA-F]+);", lambda m: chr(int(m.group(1), 16)), text)
    return text.strip()


# ---------------------------------------------------------------------------
# Step 2: Analyze
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are an AI knowledge analyst. Analyze the given item and return "
    "ONLY a valid JSON object. Do not include markdown fences or extra text."
)


def analyze_items(
    items: list[dict[str, Any]],
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Analyze each item with LLM for summary, scoring, and tagging.

    Args:
        items: Normalized items from the collect step.
        dry_run: If True, skip real LLM calls and use placeholder results.

    Returns:
        Items enriched with ``summary``, ``highlights``, ``tags``,
        ``relevance_score``, ``score_reason``, and ``category``.
    """
    analyzed: list[dict[str, Any]] = []

    for i, item in enumerate(items):
        title = item.get("title", "")[:80]
        logger.info("Analyzing %d/%d: %s", i + 1, len(items), title)

        if dry_run:
            analysis = _dry_run_analysis(item)
        else:
            analysis = _call_llm_analysis(item)

        if analysis:
            item.update(analysis)
            analyzed.append(item)
        else:
            logger.warning(
                "Skipping item due to analysis failure: %s",
                item.get("title", ""),
            )

    logger.info("Analyzed %d items.", len(analyzed))
    return analyzed


def _build_analysis_prompt(item: dict[str, Any]) -> str:
    """Build the LLM prompt for analyzing one item."""
    title = item.get("title", "")
    url = item.get("source_url", "")
    description = item.get("description", "")

    extra_lines: list[str] = []
    if item.get("source") == "github":
        extra_lines.append(f"Stars: {item.get('stars', 'N/A')}")
        extra_lines.append(f"Language: {item.get('language', 'N/A')}")
        topics = item.get("topics", [])
        if topics:
            extra_lines.append(f"Topics: {', '.join(topics[:10])}")
    extra_block = "\n".join(extra_lines)

    return (
        "Analyze the following AI-related item and return a JSON object "
        "with these fields:\n\n"
        "- summary: Concise Chinese summary (max 100 characters)\n"
        "- highlights: Array of 3 key Chinese highlights\n"
        "- tags: Array of 5-8 English lowercase tags relevant to the content\n"
        "- relevance_score: Integer 1-10 "
        "(10=most relevant to AI/LLM/Agent topics)\n"
        "- score_reason: Brief Chinese explanation for the score "
        "(max 50 characters)\n"
        "- category: One of "
        + '"tool", "framework", "library", "research", "news", "paper", "other"'
        + "\n\n"
        f"Title: {title}\n"
        f"URL: {url}\n"
        f"Description: {description}\n"
        f"{extra_block}\n\n"
        "Return ONLY the JSON object, no markdown fences, no extra text."
    )


def _call_llm_analysis(item: dict[str, Any]) -> dict[str, Any] | None:
    """Send an item to the LLM for analysis and parse the JSON response."""
    provider = get_provider()
    prompt = _build_analysis_prompt(item)

    try:
        response = chat_with_retry(
            provider,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=1024,
            max_retries=3,
        )
        content = response.content.strip()
        # Remove optional markdown code fences
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        return json.loads(content)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse LLM JSON response: %s", exc)
        return None
    except Exception as exc:
        logger.warning("LLM analysis failed: %s", exc)
        return None


def _dry_run_analysis(item: dict[str, Any]) -> dict[str, Any]:
    """Return placeholder analysis when running in dry-run mode."""
    title = item.get("title", "")[:80]
    return {
        "summary": f"[DRY-RUN] {title}",
        "highlights": [
            "[DRY-RUN] 亮点 1",
            "[DRY-RUN] 亮点 2",
            "[DRY-RUN] 亮点 3",
        ],
        "tags": ["dry-run", "test"],
        "relevance_score": 5,
        "score_reason": "[DRY-RUN] 干跑模式占位评分",
        "category": "other",
    }


# ---------------------------------------------------------------------------
# Step 3: Organize
# ---------------------------------------------------------------------------


def organize(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate, standardize, and validate items into final articles.

    Args:
        items: Analyzed items from the analyze step.

    Returns:
        Validated article dicts ready for saving.
    """
    logger.info("Organizing %d items...", len(items))

    deduped = _deduplicate(items)
    logger.info("After dedup: %d items.", len(deduped))

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    standardized: list[dict[str, Any]] = []

    for i, item in enumerate(deduped):
        try:
            article = _standardize(item, today, i + 1)
            if _validate(article):
                standardized.append(article)
            else:
                logger.warning(
                    "Validation failed, skipping: %s",
                    item.get("title", ""),
                )
        except Exception as exc:
            logger.warning("Standardization failed for item: %s", exc)

    logger.info("After organize: %d valid articles.", len(standardized))
    return standardized


def _deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove items with duplicate ``source_url`` (case-insensitive)."""
    seen: set[str] = set()
    result: list[dict[str, Any]] = []

    for item in items:
        url = item.get("source_url", "")
        if not url:
            continue
        key = url.lower().rstrip("/")
        if key not in seen:
            seen.add(key)
            result.append(item)

    return result


def _standardize(
    item: dict[str, Any], date_str: str, idx: int
) -> dict[str, Any]:
    """Convert an analyzed item into a standardized article dict.

    Args:
        item: Analyzed item dict.
        date_str: Date string in ``YYYYMMDD`` format.
        idx: 1-based index for ID generation.

    Returns:
        Standardized article dict.
    """
    source = item.get("source", "unknown")
    now = datetime.now(timezone.utc).isoformat()
    title = item.get("title", "")

    source_label = f"{source}_trending" if source == "github" else f"{source}_feed"
    score = item.get("relevance_score", 5)
    category = item.get("category", "other")
    if category not in _VALID_CATEGORIES:
        category = "other"

    return {
        "id": _generate_id(source, date_str, idx),
        "title": title,
        "source": source_label,
        "source_url": item.get("source_url", ""),
        "summary": item.get("summary", ""),
        "highlights": item.get("highlights") or [],
        "tags": item.get("tags") or [],
        "relevance_score": max(1, min(10, int(score))) if score else 5,
        "score_reason": item.get("score_reason"),
        "author": item.get("author"),
        "published_at": item.get("published_at"),
        "fetched_at": now,
        "status": "draft",
        "category": category,
        "channels": ["telegram", "feishu"],
        "slug": _slugify(title),
    }


def _generate_id(source: str, date_str: str, index: int) -> str:
    """Generate a unique article ID like ``github-20260609-001``."""
    prefix = "github" if source == "github" else "rss"
    return f"{prefix}-{date_str}-{index:03d}"


def _slugify(text: str) -> str:
    """Create a URL-friendly slug from a title string."""
    text = text.lower()
    text = text.replace("/", "-")
    # Keep alphanumeric, Chinese characters, and hyphens
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff-]", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-")


def _validate(article: dict[str, Any]) -> bool:
    """Check that an article dict has all required fields and valid values.

    Args:
        article: Article dict to validate.

    Returns:
        True if the article passes validation.
    """
    for field in _REQUIRED_FIELDS:
        if field not in article:
            logger.warning("Missing required field: %s", field)
            return False

    for field in _NONEMPTY_STRING_FIELDS:
        if not article.get(field):
            logger.warning("Empty required field: %s", field)
            return False

    url = article.get("source_url", "")
    if not url.startswith("http"):
        logger.warning("Invalid source_url: %s", url)
        return False

    score = article.get("relevance_score", 0)
    try:
        score = int(score)
    except (TypeError, ValueError):
        logger.warning("relevance_score is not an integer: %s", score)
        return False
    if not 1 <= score <= 10:
        logger.warning("relevance_score out of range: %s", score)
        return False

    tags = article.get("tags", [])
    if not isinstance(tags, list):
        logger.warning("tags is not a list")
        return False

    return True


# ---------------------------------------------------------------------------
# Step 4: Save
# ---------------------------------------------------------------------------


def save_raw(
    items: list[dict[str, Any]], sources: list[str]
) -> Path | None:
    """Save collected raw data to ``knowledge/raw/``.

    Args:
        items: Collected items from the collect step.
        sources: Source names used in this run.

    Returns:
        Path to the saved raw file, or None on failure.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"raw-{'-'.join(sources)}-{timestamp}.json"
    filepath = RAW_DIR / filename

    data: dict[str, Any] = {
        "sources": sources,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "total_count": len(items),
        "items": items,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info("Raw data saved to %s", filepath)
    return filepath


def save_articles(
    articles: list[dict[str, Any]],
    dry_run: bool = False,
) -> list[Path]:
    """Save each article as an individual JSON file to ``knowledge/articles/``.

    Args:
        articles: Standardized article dicts.
        dry_run: If True, only log what would be saved.

    Returns:
        List of saved file paths.
    """
    if not articles:
        return []

    if dry_run:
        for article in articles:
            logger.info(
                "[DRY-RUN] Would save: %s", article.get("title", "")
            )
        return []

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_dir = ARTICLES_DIR / date_str
    day_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[Path] = []

    for article in articles:
        slug = article.get("slug") or _slugify(
            article.get("title", "untitled")
        )
        filename = f"{date_str}-{slug}.json"
        filepath = day_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(article, f, ensure_ascii=False, indent=2)

        saved_paths.append(filepath)
        logger.info("Article saved: %s", filepath)

    _update_index(articles)
    return saved_paths


def _update_index(new_articles: list[dict[str, Any]]) -> None:
    """Merge new articles into ``knowledge/articles/index.json``.

    Appends new entries, sorts by ``relevance_score`` descending, and
    updates the total count.
    """
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)

    existing: dict[str, Any] = {"items": []}
    if INDEX_FILE.exists():
        try:
            with open(INDEX_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except json.JSONDecodeError:
            logger.warning("Corrupt index.json, rebuilding.")

    existing_ids = {item["id"] for item in existing.get("items", [])}

    for article in new_articles:
        if article["id"] not in existing_ids:
            existing["items"].append({
                "id": article["id"],
                "title": article["title"],
                "category": article.get("category", "other"),
                "slug": article.get("slug", ""),
                "relevance_score": article["relevance_score"],
                "status": article["status"],
                "fetched_at": article["fetched_at"],
            })

    existing["items"].sort(
        key=lambda x: x.get("relevance_score", 0), reverse=True
    )
    existing["total_count"] = len(existing["items"])
    existing["updated_at"] = datetime.now(timezone.utc).isoformat()

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    logger.info("Index updated: %d total items.", existing["total_count"])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list (uses ``sys.argv`` if None).

    Returns:
        Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Four-step knowledge base automation pipeline: "
            "Collect -> Analyze -> Organize -> Save"
        ),
    )
    parser.add_argument(
        "--sources",
        type=str,
        default="github",
        help="Comma-separated sources: github, rss (default: github)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Max items to collect per source (default: 10)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run pipeline without saving files or making real LLM calls",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose (DEBUG level) logging",
    )
    return parser.parse_args(argv)


def setup_logging(verbose: bool = False) -> None:
    """Configure logging with appropriate level and format."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------


def run_pipeline(
    sources: list[str],
    limit: int = 10,
    dry_run: bool = False,
) -> int:
    """Run the full 4-step pipeline programmatically.

    Args:
        sources: List of source names (``github`` and/or ``rss``).
        limit: Max items to collect per source.
        dry_run: If True, skip real LLM calls and file writes.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    # --- Step 1: Collect ---
    items: list[dict[str, Any]] = []

    for source in sources:
        if source == "github":
            items.extend(collect_github(limit=limit))
        elif source == "rss":
            items.extend(collect_rss(limit=limit))
        else:
            logger.warning("Unknown source skipped: %s", source)

    if not items:
        logger.warning("No items collected from sources: %s", sources)
        return 0

    if not dry_run:
        save_raw(items, sources)

    # --- Step 2: Analyze ---
    logger.info("Step 2: Analyzing %d items...", len(items))
    analyzed = analyze_items(items, dry_run=dry_run)

    if not analyzed:
        logger.warning("No items survived analysis.")
        return 0

    # --- Step 3: Organize ---
    logger.info("Step 3: Organizing...")
    organized = organize(analyzed)

    if not organized:
        logger.warning("No items survived organizing.")
        return 0

    # --- Step 4: Save ---
    logger.info("Step 4: Saving %d articles...", len(organized))
    saved = save_articles(organized, dry_run=dry_run)

    logger.info(
        "Pipeline completed. "
        "Collected=%d, Analyzed=%d, Organized=%d, Saved=%d.",
        len(items),
        len(analyzed),
        len(organized),
        len(saved),
    )

    if not dry_run:
        cost_tracker.report()

    return 0


def main() -> int:
    """CLI entry point. Parses args and runs the pipeline."""
    args = parse_args()
    setup_logging(verbose=args.verbose)

    sources = [s.strip() for s in args.sources.split(",")]

    logger.info("=== Pipeline Start ===")
    logger.info(
        "Sources: %s, Limit: %d, Dry-run: %s",
        sources,
        args.limit,
        args.dry_run,
    )

    exit_code = run_pipeline(
        sources=sources,
        limit=args.limit,
        dry_run=args.dry_run,
    )

    logger.info("=== Pipeline End ===")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
