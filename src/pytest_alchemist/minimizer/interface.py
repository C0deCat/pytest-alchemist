"""Shared minimizer interface."""

from typing import Protocol

from pytest_alchemist.minimizer.models import MinimizationInput, MinimizationResult


class MinimizerInterface(Protocol):
    """Common interface implemented by concrete minimizers."""

    def minimize(
        self,
        input_data: MinimizationInput,
        seed: int | None = None,
        runtime_tolerance_ms: int = 10,
    ) -> MinimizationResult:
        """Return a minimized test subset for prepared factual input."""
