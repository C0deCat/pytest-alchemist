"""Models for changed code selection."""

from dataclasses import dataclass

from pytest_alchemist.coverage_analysis.models import CoverageRecord
from pytest_alchemist.test_runner.models import TestCase


@dataclass(frozen=True)
class ChangedCode:
    """Changed lines in a file."""

    file_path: str
    lines: list[int]


@dataclass(frozen=True)
class TestSelection:
    """Candidate tests and target changes selected from a diff."""

    candidates: list[TestCase]
    target_changes: list[ChangedCode]
    coverage_records: list[CoverageRecord]
