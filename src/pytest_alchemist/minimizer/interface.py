"""Shared minimizer interface."""

from typing import Literal, Protocol

from pytest_alchemist.minimizer.evaluators import CoverageEvaluation
from pytest_alchemist.minimizer.models import MinimizationInput, MinimizationResult

OptimizerName = Literal["mopso", "greedy"]

# Internal interface which each optimizer (greedy, MOPSO, etc.) must implement to be used by the main Minimizer
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

# External interface for interactions with application module
class MinimizerInterface(Protocol):
    """Common interface implemented by concrete minimizers."""

    def minimize(
        self,
        input_data: MinimizationInput,
        seed: int | None = None,
        runtime_tolerance_ms: int = 10,
    ) -> MinimizationResult:
        """Return a minimized test subset for prepared factual input."""
