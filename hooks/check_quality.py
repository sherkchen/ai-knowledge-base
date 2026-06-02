#!/usr/bin/env python3
"""5-dimension quality scoring for knowledge article JSON files.

Usage:
    python hooks/check_quality.py <json_file> [json_file2 ...]
    python hooks/check_quality.py knowledge/articles/2026-05-30/*.json

Exit code 0 when all files score A or B, 1 if any scores C.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BAR_WIDTH = 20
BAR_FILL = "█"
BAR_EMPTY = "░"

GRADE_A_THRESHOLD = 80
GRADE_B_THRESHOLD = 60

ID_PATTERN = re.compile(r"^[a-z]+-\d{8}-\d{3}$")
URL_PATTERN = re.compile(r"^https?://\S+$")
ISO_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

VALID_STATUSES = frozenset({"draft", "review", "published", "archived"})

# ---------------------------------------------------------------------------
# Chinese + English buzzword / hollow-word blacklist
# ---------------------------------------------------------------------------

BUZZWORDS_CN = frozenset({
    "赋能", "抓手", "闭环", "打通", "全链路", "底层逻辑",
    "颗粒度", "对齐", "拉通", "沉淀", "强大的",
})

BUZZWORDS_EN = frozenset({
    "groundbreaking", "revolutionary", "game-changing", "cutting-edge",
    "next-generation", "best-in-class", "world-class", "disruptive",
    "paradigm-shifting", "unprecedented",
})

# ---------------------------------------------------------------------------
# Standard / canonical tags list for tag-precision validation
# ---------------------------------------------------------------------------

STANDARD_TAGS = frozenset({
    "agent", "llm", "rag", "vector-database", "embedding", "fine-tuning",
    "workflow", "low-code", "platform", "framework", "tool",
    "api", "open-source", "memory", "multi-agent", "orchestration",
    "ui", "chatbot", "knowledge-base", "documents", "search",
    "data", "etl", "real-time", "training", "inference",
    "deployment", "monitoring", "observability", "security",
    "multimodal", "nlp", "code-generation", "evaluation",
    "self-evolving", "skills", "multi-channel", "automation",
    "llmops", "personalization", "similarity-search",
})

# ---------------------------------------------------------------------------
# Technical keywords used for summary-quality bonus
# ---------------------------------------------------------------------------

TECH_KEYWORDS = frozenset({
    "ai", "llm", "gpt", "rag", "agent",
    "智能体", "大模型", "大语言模型", "语言模型",
    "向量", "向量数据库", "embedding", "嵌入",
    "微调", "fine-tuning", "fine-tune",
    "api", "开源", "open-source",
    "框架", "framework", "平台", "platform", "工具", "tool",
    "模型", "model", "推理", "inference",
    "训练", "training", "部署", "deployment",
    "多模态", "multimodal", "transformer",
    "深度学习", "deep-learning", "机器学习", "machine-learning",
    "nlp", "自然语言", "自然语言处理",
    "知识图谱", "knowledge-graph",
    "检索增强", "检索增强生成",
    "langchain", "pipeline", "流水线",
    "工作流", "workflow", "自动化", "automation",
    "编排", "orchestration", "可视化",
    "自我改进", "self-improving", "自主", "autonomous",
    "记忆", "memory", "技能", "skill",
    "通道", "channel", "通讯", "communication",
    "低代码", "low-code", "数据分析",
    "实时", "real-time", "流式", "streaming",
})


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DimensionScore:
    name: str
    score: float
    max_score: int
    details: list[str] = field(default_factory=list)


@dataclass
class QualityReport:
    filepath: str
    dimensions: list[DimensionScore] = field(default_factory=list)
    parse_error: str | None = None

    @property
    def total_score(self) -> float:
        return sum(d.score for d in self.dimensions)

    @property
    def max_total(self) -> int:
        return sum(d.max_score for d in self.dimensions)

    @property
    def grade(self) -> str:
        s = self.total_score
        if s >= GRADE_A_THRESHOLD:
            return "A"
        if s >= GRADE_B_THRESHOLD:
            return "B"
        return "C"


# ---------------------------------------------------------------------------
# File helpers (self-contained, aligned with validate_json.py)
# ---------------------------------------------------------------------------

def collect_files(args: list[str]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()

    for arg in args:
        path = Path(arg)
        if path.is_file() and path.suffix == ".json":
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                files.append(resolved)
        elif path.is_dir():
            for child in sorted(path.iterdir()):
                if child.is_file() and child.suffix == ".json":
                    resolved = child.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        files.append(resolved)
        else:
            resolved_parent = path.parent.resolve()
            pattern = path.name
            if not resolved_parent.is_dir():
                continue
            for child in sorted(resolved_parent.glob(pattern)):
                if child.is_file() and child.suffix == ".json":
                    resolved = child.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        files.append(resolved)
    return files


def load_json(filepath: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        text = filepath.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"cannot read file: {exc}"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(data, dict):
        return None, f"top-level value must be a JSON object, got {type(data).__name__}"
    return data, None


# ---------------------------------------------------------------------------
# Dimension 1 — Summary quality (max 25)
# ---------------------------------------------------------------------------

def score_summary(data: dict[str, Any]) -> DimensionScore:
    dim = DimensionScore(name="摘要质量", score=0, max_score=25)
    summary = data.get("summary", "")
    if not isinstance(summary, str):
        dim.details.append("summary missing or not a string → 0")
        return dim

    length = len(summary)

    if length >= 50:
        base = 20
        dim.details.append(f"长度 {length} >= 50 → 基础分 20")
    elif length >= 20:
        base = 10
        dim.details.append(f"长度 {length} >= 20 → 基础分 10")
    else:
        base = 0
        dim.details.append(f"长度 {length} < 20 → 基础分 0")

    summary_lower = summary.lower()
    found_keywords: list[str] = []
    for kw in TECH_KEYWORDS:
        if kw in summary_lower:
            found_keywords.append(kw)
            if len(found_keywords) >= 5:
                break

    bonus = min(len(found_keywords), 5)
    if found_keywords:
        dim.details.append(
            f"技术关键词 {len(found_keywords)} 个 ({', '.join(found_keywords[:6])})"
            f" → 奖励 +{bonus}"
        )
    else:
        dim.details.append("未检测到技术关键词 → 奖励 +0")

    dim.score = min(base + bonus, 25)
    return dim


# ---------------------------------------------------------------------------
# Dimension 2 — Technical depth (max 25)
# ---------------------------------------------------------------------------

def score_technical_depth(data: dict[str, Any]) -> DimensionScore:
    dim = DimensionScore(name="技术深度", score=0, max_score=25)
    highlights = data.get("highlights")
    if not isinstance(highlights, list) or len(highlights) == 0:
        dim.details.append("highlights 缺失或为空列表 → 0")
        return dim

    valid_items: list[str] = []
    for h in highlights:
        if isinstance(h, str) and len(h.strip()) > 0:
            valid_items.append(h)

    item_count = len(valid_items)
    if item_count == 0:
        dim.details.append("highlights 无有效条目 → 0")
        return dim

    # Count score: 5 points per highlight, max 15 (3 items)
    count_score = min(item_count, 3) * 5
    dim.details.append(f"有效条目 {item_count} 条 → 数量分 {count_score}")

    # Detail score: based on average highlight length, max 5
    total_chars = sum(len(h) for h in valid_items)
    avg_len = total_chars / item_count
    if avg_len >= 30:
        detail_score = 5
    elif avg_len >= 20:
        detail_score = 3
    elif avg_len >= 10:
        detail_score = 1
    else:
        detail_score = 0
    dim.details.append(f"平均长度 {avg_len:.0f} 字 → 细节分 +{detail_score}")

    # Technical keyword bonus: up to 5
    all_text = " ".join(valid_items).lower()
    found: set[str] = set()
    for kw in TECH_KEYWORDS:
        if kw in all_text:
            found.add(kw)
            if len(found) >= 5:
                break
    kw_bonus = len(found)
    if found:
        dim.details.append(
            f"技术关键词 {len(found)} 个 ({', '.join(sorted(found)[:6])})"
            f" → 奖励 +{kw_bonus}"
        )
    else:
        dim.details.append("未检测到技术关键词 → 奖励 +0")

    dim.score = min(count_score + detail_score + kw_bonus, 25)
    return dim


# ---------------------------------------------------------------------------
# Dimension 3 — Format specification (max 20)
# ---------------------------------------------------------------------------

def _check_id_format(data: dict[str, Any]) -> tuple[int, str]:
    article_id = data.get("id")
    if isinstance(article_id, str) and ID_PATTERN.match(article_id):
        return 4, "id 格式正确"
    return 0, "id 格式不符"


def _check_title(data: dict[str, Any]) -> tuple[int, str]:
    title = data.get("title")
    if isinstance(title, str) and len(title.strip()) > 0:
        return 4, "title 存在且非空"
    return 0, "title 缺失或为空"


def _check_source_url(data: dict[str, Any]) -> tuple[int, str]:
    url = data.get("source_url")
    if isinstance(url, str) and URL_PATTERN.match(url):
        return 4, "source_url 格式正确"
    return 0, "source_url 格式不符"


def _check_status(data: dict[str, Any]) -> tuple[int, str]:
    status = data.get("status")
    if isinstance(status, str) and status in VALID_STATUSES:
        return 4, f"status={status} 合法"
    return 0, "status 缺失或不合法"


def _check_timestamp(data: dict[str, Any]) -> tuple[int, str]:
    for field in ("fetched_at", "published_at"):
        ts = data.get(field)
        if isinstance(ts, str) and ISO_PATTERN.match(ts):
            return 4, f"{field} 时间戳有效"
    return 0, "缺少有效的时间戳字段 (fetched_at / published_at)"


def score_format(data: dict[str, Any]) -> DimensionScore:
    dim = DimensionScore(name="格式规范", score=0, max_score=20)
    checks = [
        _check_id_format(data),
        _check_title(data),
        _check_source_url(data),
        _check_status(data),
        _check_timestamp(data),
    ]
    for points, note in checks:
        dim.score += points
        dim.details.append(f"[{'✓' if points else '✗'}] {note}  ({points}/4)")
    return dim


# ---------------------------------------------------------------------------
# Dimension 4 — Tag precision (max 15)
# ---------------------------------------------------------------------------

def score_tags(data: dict[str, Any]) -> DimensionScore:
    dim = DimensionScore(name="标签精度", score=0, max_score=15)
    tags = data.get("tags")
    if not isinstance(tags, list) or len(tags) == 0:
        dim.details.append("tags 缺失或为空 → 0")
        return dim

    count = len(tags)
    if 1 <= count <= 3:
        base = 10
    elif 4 <= count <= 5:
        base = 8
    else:
        base = 5

    matched = sum(1 for t in tags if isinstance(t, str) and t.lower() in STANDARD_TAGS)
    ratio = matched / count if count > 0 else 0
    bonus = round(ratio * 5)

    dim.score = min(base + bonus, 15)
    dim.details.append(
        f"{count} 个标签, {matched}/{count} 命中标准库"
        f" → 基础 {base} + 命中奖励 {bonus}"
    )
    return dim


# ---------------------------------------------------------------------------
# Dimension 5 — Buzzword / hollow-word detection (max 15)
# ---------------------------------------------------------------------------

def score_buzzwords(data: dict[str, Any]) -> DimensionScore:
    dim = DimensionScore(name="空洞词检测", score=15, max_score=15)
    summary = data.get("summary", "")
    highlights = data.get("highlights", [])
    reason = data.get("score_reason", "")

    corpus = ""
    if isinstance(summary, str):
        corpus += summary
    if isinstance(highlights, list):
        corpus += " ".join(h for h in highlights if isinstance(h, str))
    if isinstance(reason, str):
        corpus += reason

    found: list[str] = []

    for bw in BUZZWORDS_CN:
        if bw in corpus:
            found.append(bw)
    corpus_lower = corpus.lower()
    for bw in BUZZWORDS_EN:
        if bw.lower() in corpus_lower:
            found.append(bw)

    penalty = len(found) * 3
    dim.score = max(15 - penalty, 0)

    if found:
        dim.details.append(f"检测到 {len(found)} 个空洞词: {', '.join(found)} → -{penalty}")
    else:
        dim.details.append("未检测到空洞词")

    return dim


# ---------------------------------------------------------------------------
# Put it together
# ---------------------------------------------------------------------------

def score_file(filepath: Path) -> QualityReport:
    report = QualityReport(filepath=str(filepath))
    data, error = load_json(filepath)
    if error:
        report.parse_error = error
        return report

    report.dimensions = [
        score_summary(data),
        score_technical_depth(data),
        score_format(data),
        score_tags(data),
        score_buzzwords(data),
    ]
    return report


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _bar(score: float, maximum: int, width: int = BAR_WIDTH) -> str:
    ratio = min(score / maximum, 1.0) if maximum > 0 else 0
    filled = round(ratio * width)
    return BAR_FILL * filled + BAR_EMPTY * (width - filled)


def _grade_color(grade: str) -> str:
    if grade == "A":
        return "\033[32m"  # green
    if grade == "C":
        return "\033[31m"  # red
    return "\033[33m"  # yellow


_RESET = "\033[0m"


def print_progress(current: int, total: int) -> None:
    pct = (current / total * 100) if total > 0 else 0
    bar = _bar(current, total, width=30)
    sys.stdout.write(f"\r  处理进度  [{bar}] {current}/{total}  ({pct:.0f}%)")
    sys.stdout.flush()


def print_report(report: QualityReport) -> None:
    short = Path(report.filepath).name
    print(f"\n{'─' * 56}")
    print(f"  📄 {short}")

    if report.parse_error:
        print(f"  ⚠ 解析失败: {report.parse_error}")
        return

    for dim in report.dimensions:
        bar = _bar(dim.score, dim.max_score)
        print(f"  [{bar}] {dim.name:6s}  {dim.score:5.1f}/{dim.max_score}")
        for detail in dim.details:
            print(f"    {detail}")

    total = report.total_score
    grade = report.grade
    color = _grade_color(grade)
    print(f"  {'─' * 50}")
    print(f"  总分: {color}{total:.1f}/100{_RESET}  等级: {color}{grade}{_RESET}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv

    if len(argv) < 2:
        print(f"Usage: python {argv[0]} <json_file> [json_file2 ...]")
        return 1

    files = collect_files(argv[1:])
    if not files:
        print("No JSON files found matching the given arguments.")
        return 1

    print(f"\n  开始评测 {len(files)} 个知识条目\n")

    reports: list[QualityReport] = []
    counts: dict[str, int] = {"A": 0, "B": 0, "C": 0}
    errors = 0

    for idx, filepath in enumerate(files, 1):
        print_progress(idx, len(files))
        report = score_file(filepath)
        reports.append(report)
        if report.parse_error:
            errors += 1
        else:
            counts[report.grade] += 1

    print()  # final newline after progress bar

    for report in reports:
        print_report(report)

    # Summary
    print(f"\n{'=' * 56}")
    print(f"  评测汇总")
    print(f"  {'─' * 50}")
    print(f"  文件总数: {len(files)}")
    print(f"  解析失败: {errors}")
    print(f"  等级分布: A={counts['A']}  B={counts['B']}  C={counts['C']}")

    if reports and counts["C"] == 0 and errors == 0:
        all_scores = [r.total_score for r in reports if r.dimensions]
        avg = sum(all_scores) / len(all_scores) if all_scores else 0
        print(f"  平均分: {avg:.1f}")
        print(f"\n  ✅ 全部达标 (无 C 级)")
    elif errors > 0 and counts["C"] > 0:
        print(f"\n  ⚠ 存在 {counts['C']} 个 C 级条目且 {errors} 个文件解析失败，需改进")
    elif errors > 0:
        print(f"\n  ⚠ 存在 {errors} 个文件解析失败，需检查")
    else:
        print(f"\n  ⚠ 存在 {counts['C']} 个 C 级条目，需改进")

    print(f"{'=' * 56}\n")

    return 0 if counts["C"] == 0 and errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
