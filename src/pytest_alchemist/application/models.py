"""Application-level orchestration models."""

from dataclasses import dataclass

from pytest_alchemist.minimizer.models import MinimizationResult


@dataclass(frozen=True)
class MinimizerComparisonEntry:
    """One optimizer result in a minimizer comparison."""

    optimizer_name: str
    result: MinimizationResult


@dataclass(frozen=True)
class MinimizerComparison:
    """Results from running multiple optimizers over one minimization input."""

    entries: list[MinimizerComparisonEntry]
