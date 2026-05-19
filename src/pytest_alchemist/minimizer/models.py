"""Models used by minimizers."""

from dataclasses import dataclass

from pytest_alchemist.coverage_analysis.models import CoverageRecord
from pytest_alchemist.diff_picker.models import ChangedCode
from pytest_alchemist.test_runner.models import TestCase


@dataclass(frozen=True)
class MinimizationInput:
    """Input data for a minimization algorithm."""

    candidates: list[TestCase]
    target_changes: list[ChangedCode]
    coverage_records: list[CoverageRecord]


@dataclass(frozen=True)
class MinimizationResult:
    """Selected tests returned by a minimization algorithm."""

    selected_tests: list[TestCase]
    reason: str
    coverage_percent: float
    uncovered_target_count: int
    selected_test_count: int
    estimated_runtime: float
    seed: int
