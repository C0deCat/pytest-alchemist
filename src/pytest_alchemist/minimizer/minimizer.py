"""Public minimizer orchestration."""

from pytest_alchemist.minimizer.evaluators import build_coverage_evaluation
from pytest_alchemist.minimizer.models import MinimizationInput, MinimizationResult
from pytest_alchemist.minimizer.mopso import MOPSOOptimizer


class Minimizer:
    """Select a minimal test subset from already prepared input data."""

    def __init__(self, optimizer: MOPSOOptimizer | None = None) -> None:
        self._optimizer = optimizer or MOPSOOptimizer()

    def minimize(
        self,
        input_data: MinimizationInput,
        seed: int | None = None,
        runtime_tolerance_ms: int = 10,
    ) -> MinimizationResult:
        """Select a feasible changed-line-covering subset of candidate tests."""

        evaluation = build_coverage_evaluation(input_data)
        return self._optimizer.minimize(
            input_data=input_data,
            evaluation=evaluation,
            seed=seed,
            runtime_tolerance_ms=runtime_tolerance_ms,
        )
