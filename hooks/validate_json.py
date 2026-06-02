#!/usr/bin/env python3
"""Validate knowledge article JSON files.

Usage:
    python hooks/validate_json.py <json_file> [json_file2 ...]
    python hooks/validate_json.py knowledge/articles/2026-05-30/*.json

Exit code 0 when all files pass validation, 1 otherwise.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REQUIRED_FIELDS: dict[str, type] = {
    "id": str,
    "title": str,
    "source_url": str,
    "summary": str,
    "tags": list,
    "status": str,
}

ID_PATTERN = re.compile(r"^[a-z]+-\d{8}-\d{3}$")
URL_PATTERN = re.compile(r"^https?://\S+$")
SUMMARY_MIN_CHARS = 20
VALID_STATUSES = frozenset({"draft", "review", "published", "archived"})
VALID_AUDIENCES = frozenset({"beginner", "intermediate", "advanced"})
SCORE_MIN = 1
SCORE_MAX = 10


@dataclass
class ValidationReport:
    filepath: str
    errors: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def add(self, message: str) -> None:
        self.errors.append(message)


def collect_files(args: list[str]) -> list[Path]:
    """Resolve all given paths/globs into a deduplicated sorted list of .json files."""
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
                report = ValidationReport(filepath=arg)
                report.add(f"path does not exist: {path}")
                return [path.resolve()]
            for child in sorted(resolved_parent.glob(pattern)):
                if child.is_file() and child.suffix == ".json":
                    resolved = child.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        files.append(resolved)

    return files


def load_json(filepath: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Parse a JSON file and return (data, error_message)."""
    try:
        text = filepath.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"cannot read file: {exc}"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(data, dict):
        return None, "top-level value must be a JSON object, got {type(data).__name__}"
    return data, None


def validate_required_fields(data: dict[str, Any], report: ValidationReport) -> None:
    """Check that every required field exists and has the correct type."""
    for field_name, field_type in REQUIRED_FIELDS.items():
        if field_name not in data:
            report.add(f"missing required field: {field_name}")
            continue
        value = data[field_name]
        if not isinstance(value, field_type):
            report.add(
                f"field {field_name}: expected {field_type.__name__}, "
                f"got {type(value).__name__}"
            )


def validate_id(data: dict[str, Any], report: ValidationReport) -> None:
    """Validate the id field format: {source}-{YYYYMMDD}-{NNN}."""
    if "id" not in data or not isinstance(data["id"], str):
        return
    article_id: str = data["id"]
    if not ID_PATTERN.match(article_id):
        report.add(
            f"invalid id format: {article_id!r} "
            f"(expected pattern: {{source}}-{{YYYYMMDD}}-{{NNN}}, e.g. github-20260317-001)"
        )


def validate_status(data: dict[str, Any], report: ValidationReport) -> None:
    """Validate status is one of draft/review/published/archived."""
    if "status" not in data or not isinstance(data["status"], str):
        return
    status_value: str = data["status"]
    if status_value not in VALID_STATUSES:
        report.add(
            f"invalid status: {status_value!r} "
            f"(must be one of: {', '.join(sorted(VALID_STATUSES))})"
        )


def validate_source_url(data: dict[str, Any], report: ValidationReport) -> None:
    """Validate source_url is a well-formed http/https URL."""
    if "source_url" not in data or not isinstance(data["source_url"], str):
        return
    url: str = data["source_url"]
    if not URL_PATTERN.match(url):
        report.add(f"invalid source_url: {url!r}")


def validate_summary(data: dict[str, Any], report: ValidationReport) -> None:
    """Validate summary has at least SUMMARY_MIN_CHARS characters."""
    if "summary" not in data or not isinstance(data["summary"], str):
        return
    summary: str = data["summary"]
    if len(summary) < SUMMARY_MIN_CHARS:
        report.add(
            f"summary too short: {len(summary)} characters "
            f"(minimum {SUMMARY_MIN_CHARS})"
        )


def validate_tags(data: dict[str, Any], report: ValidationReport) -> None:
    """Validate tags is a non-empty list of strings."""
    if "tags" not in data or not isinstance(data["tags"], list):
        return
    tags: list[Any] = data["tags"]
    if len(tags) < 1:
        report.add("tags must contain at least 1 item")
    for idx, tag in enumerate(tags):
        if not isinstance(tag, str):
            report.add(f"tags[{idx}] must be a string, got {type(tag).__name__}")


def validate_score(data: dict[str, Any], report: ValidationReport) -> None:
    """Validate relevance_score is in 1..10 (if present)."""
    score = data.get("relevance_score")
    if score is None:
        return
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        report.add(
            f"relevance_score must be a number, got {type(score).__name__}"
        )
        return
    if score < SCORE_MIN or score > SCORE_MAX:
        report.add(
            f"relevance_score out of range: {score} "
            f"(must be {SCORE_MIN}..{SCORE_MAX})"
        )


def validate_audience(data: dict[str, Any], report: ValidationReport) -> None:
    """Validate audience is beginner/intermediate/advanced (if present)."""
    audience = data.get("audience")
    if audience is None:
        return
    if not isinstance(audience, str):
        report.add(f"audience must be a string, got {type(audience).__name__}")
        return
    if audience not in VALID_AUDIENCES:
        report.add(
            f"invalid audience: {audience!r} "
            f"(must be one of: {', '.join(sorted(VALID_AUDIENCES))})"
        )


def validate_file(filepath: Path) -> ValidationReport:
    """Run all validations on a single JSON file."""
    report = ValidationReport(filepath=str(filepath))
    data, error = load_json(filepath)
    if error:
        report.add(error)
        return report

    validate_required_fields(data, report)
    validate_id(data, report)
    validate_status(data, report)
    validate_source_url(data, report)
    validate_summary(data, report)
    validate_tags(data, report)
    validate_score(data, report)
    validate_audience(data, report)
    return report


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

    reports: list[ValidationReport] = []
    passed = 0
    failed = 0
    total_errors = 0

    for filepath in files:
        report = validate_file(filepath)
        reports.append(report)
        if report.is_valid:
            passed += 1
        else:
            failed += 1
            total_errors += len(report.errors)

    # Print error details
    for report in reports:
        if not report.is_valid:
            print(f"\n{'=' * 60}")
            print(f"FAIL  {report.filepath}")
            print(f"{'-' * 60}")
            for idx, error in enumerate(report.errors, 1):
                print(f"  [{idx}] {error}")

    # Print summary
    print(f"\n{'=' * 60}")
    print(f"Summary: {len(files)} file(s) checked")
    print(f"  Passed: {passed}")
    print(f"  Failed: {failed}")
    print(f"  Errors: {total_errors}")
    print(f"{'=' * 60}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
