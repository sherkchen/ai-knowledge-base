#!/usr/bin/env python3
"""Validate RSS sources YAML configuration file.

Usage::

    python pipeline/validate_rss_sources.py pipeline/rss_sources.yaml
    python pipeline/validate_rss_sources.py -q pipeline/rss_sources.yaml

Exit code 0 when the file passes all validations, 1 otherwise.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REQUIRED_FIELDS: set[str] = {"name", "url", "category", "enabled"}

VALID_CATEGORIES: frozenset[str] = frozenset({
    "news", "paper", "research", "tool", "framework", "library", "other",
})

URL_PATTERN = re.compile(r"^https?://\S+\.\S+$")

NAME_MIN_LENGTH = 2
NAME_MAX_LENGTH = 80

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ValidationReport:
    """Accumulates validation errors for one YAML file."""

    filepath: str
    errors: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def add(self, message: str) -> None:
        self.errors.append(message)


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


def load_yaml(filepath: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Load and parse the YAML file.

    Returns:
        Tuple of ``(data, error)``.  One of them is always None.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        return None, f"file not found: {filepath}"
    except yaml.YAMLError as exc:
        return None, f"YAML parse error: {exc}"
    except Exception as exc:
        return None, f"unexpected error reading file: {exc}"

    if data is None:
        return None, "file is empty (no YAML documents)"

    if not isinstance(data, dict):
        return None, f"expected a top-level mapping, got {type(data).__name__}"

    return data, None


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def validate_top_level(data: dict[str, Any], report: ValidationReport) -> None:
    """Check that the top-level ``sources`` key exists and is a list."""
    if "sources" not in data:
        report.add('missing top-level key "sources"')
        return
    if not isinstance(data["sources"], list):
        report.add(f'"sources" must be a list, got {type(data["sources"]).__name__}')
        return
    if len(data["sources"]) == 0:
        report.add('"sources" list is empty')


def validate_source_entry(
    entry: Any, index: int, report: ValidationReport, seen_names: set[str]
) -> None:
    """Validate a single source entry."""
    prefix = f"sources[{index}]"

    if not isinstance(entry, dict):
        report.add(f"{prefix}: expected a mapping, got {type(entry).__name__}")
        return

    # --- required fields ---
    for field in sorted(REQUIRED_FIELDS):
        if field not in entry:
            report.add(f'{prefix}: missing required field "{field}"')
        elif entry[field] is None:
            report.add(f'{prefix}: field "{field}" is null')

    if not report.is_valid:
        return

    # --- name ---
    name = entry.get("name", "")
    if not isinstance(name, str):
        report.add(f'{prefix}: "name" must be a string, got {type(name).__name__}')
    else:
        if len(name) < NAME_MIN_LENGTH:
            report.add(
                f'{prefix}: "name" too short ({len(name)} < {NAME_MIN_LENGTH}): {name!r}'
            )
        if len(name) > NAME_MAX_LENGTH:
            report.add(
                f'{prefix}: "name" too long ({len(name)} > {NAME_MAX_LENGTH}): {name!r}'
            )
        if name in seen_names:
            report.add(f'{prefix}: duplicate name {name!r}')
        else:
            seen_names.add(name)

    # --- url ---
    url = entry.get("url", "")
    if not isinstance(url, str):
        report.add(f'{prefix}: "url" must be a string, got {type(url).__name__}')
    elif not url:
        report.add(f'{prefix}: "url" is empty')
    elif not URL_PATTERN.match(url):
        report.add(f'{prefix}: "url" does not look like a valid URL: {url!r}')

    # --- category ---
    category = entry.get("category", "")
    if not isinstance(category, str):
        report.add(
            f'{prefix}: "category" must be a string, got {type(category).__name__}'
        )
    elif not category:
        report.add(f'{prefix}: "category" is empty')
    elif category not in VALID_CATEGORIES:
        report.add(
            f'{prefix}: invalid category {category!r} '
            f"(must be one of: {', '.join(sorted(VALID_CATEGORIES))})"
        )

    # --- enabled ---
    enabled = entry.get("enabled")
    if not isinstance(enabled, bool):
        report.add(
            f'{prefix}: "enabled" must be a boolean, got {type(enabled).__name__} '
            f"({enabled!r})"
        )


def validate_sources(data: dict[str, Any], report: ValidationReport) -> None:
    """Iterate over the ``sources`` list and validate each entry."""
    sources = data.get("sources", [])
    if not isinstance(sources, list):
        return

    seen_names: set[str] = set()
    for i, entry in enumerate(sources):
        validate_source_entry(entry, i, report, seen_names)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def validate_file(filepath: Path) -> ValidationReport:
    """Run all validations on a single YAML file.

    Args:
        filepath: Path to the RSS sources YAML file.

    Returns:
        A :class:`ValidationReport` describing all issues found.
    """
    report = ValidationReport(filepath=str(filepath))

    data, error = load_yaml(filepath)
    if error:
        report.add(error)
        return report

    validate_top_level(data, report)
    validate_sources(data, report)
    return report


def print_report(report: ValidationReport, quiet: bool = False) -> None:
    """Print validation results to stdout.

    Args:
        report: The validation report to print.
        quiet: If True, only print failures.
    """
    if report.is_valid:
        if not quiet:
            print(f"OK  {report.filepath}")
        return

    print(f"\n{'=' * 60}")
    print(f"FAIL  {report.filepath}")
    print(f"{'-' * 60}")
    for idx, error in enumerate(report.errors, 1):
        print(f"  [{idx}] {error}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> tuple[Path, bool]:
    """Parse command-line arguments.

    Returns:
        Tuple of ``(filepath, quiet)``.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Validate RSS sources YAML configuration file."
    )
    parser.add_argument(
        "yaml_file",
        type=Path,
        help="Path to rss_sources.yaml",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Only print validation failures (suppress OK messages)",
    )
    args = parser.parse_args(argv)
    return args.yaml_file, args.quiet


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Validates the given YAML file and returns exit code."""
    yaml_path, quiet = parse_args(argv)

    if not yaml_path.exists():
        print(f"Error: file not found: {yaml_path}")
        return 1

    report = validate_file(yaml_path)
    print_report(report, quiet=quiet)

    if not report.is_valid:
        print(f"\n{'=' * 60}")
        print(f"Validation failed with {len(report.errors)} error(s).")
        print(f"{'=' * 60}")

    return 0 if report.is_valid else 1


if __name__ == "__main__":
    sys.exit(main())
