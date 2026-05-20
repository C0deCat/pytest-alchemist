"""Application-level orchestration models."""

from dataclasses import dataclass
from pathlib import Path

from pytest_alchemist.minimizer.models import MinimizationResult


@dataclass(frozen=True)
class GitSnapshot:
    """Git metadata captured for a persisted project run."""

    branch: str | None
    commit: str | None
    is_dirty: bool | None


@dataclass(frozen=True)
class ProjectStatus:
    """Dashboard-ready status for a pytest-alchemist project."""

    project_path: Path
    latest_coverage_run_uid: str | None
    latest_coverage_created_at: str | None
    latest_coverage_quality: str | None
    latest_run_uid: str | None
    latest_run_finished_at: str | None
    latest_run_status: str | None
    coverage_entity_count: int
    coverage_line_fact_count: int
    coverage_arc_fact_count: int
    known_test_count: int
    git: GitSnapshot


@dataclass(frozen=True)
class MinimizerComparisonEntry:
    """One optimizer result in a minimizer comparison."""

    optimizer_name: str
    result: MinimizationResult


@dataclass(frozen=True)
class MinimizerComparison:
    """Results from running multiple optimizers over one minimization input."""

    entries: list[MinimizerComparisonEntry]
