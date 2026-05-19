"""Shared minimizer interface."""

from typing import Literal, Protocol

from pytest_alchemist.minimizer.evaluators import CoverageEvaluation
from pytest_alchemist.minimizer.models import MinimizationInput, MinimizationResult

OptimizerName = Literal["mopso", "greedy"]


class OptimizerInterface(Protocol):
    """Common interface implemented by concrete minimizer optimizers."""

    def minimize(
        self,
        input_data: MinimizationInput,
        evaluation: CoverageEvaluation,
        seed: int | None = None,
        runtime_tolerance_ms: int = 10,
    ) -> MinimizationResult:
        """Return a minimized subset from precomputed coverage facts."""


class MinimizerInterface(Protocol):
    """Common interface implemented by concrete minimizers."""

    def minimize(
        self,
        input_data: MinimizationInput,
        seed: int | None = None,
        runtime_tolerance_ms: int = 10,
    ) -> MinimizationResult:
        """Return a minimized test subset for prepared factual input."""
