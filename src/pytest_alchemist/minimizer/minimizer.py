"""Public minimizer orchestration."""

from pytest_alchemist.minimizer.evaluators import build_coverage_evaluation
from pytest_alchemist.minimizer.greedy import GreedyOptimizer
from pytest_alchemist.minimizer.interface import OptimizerInterface, OptimizerName
from pytest_alchemist.minimizer.models import MinimizationInput, MinimizationResult
from pytest_alchemist.minimizer.mopso import MOPSOOptimizer


class Minimizer:
    """Select a minimal test subset from already prepared input data."""

    def __init__(
        self,
        optimizer: OptimizerName | OptimizerInterface = "mopso",
    ) -> None:
        self._optimizer = _resolve_optimizer(optimizer)

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


def _resolve_optimizer(
    optimizer: OptimizerName | OptimizerInterface,
) -> OptimizerInterface:
    if isinstance(optimizer, str):
        if optimizer == "mopso":
            return MOPSOOptimizer()
        if optimizer == "greedy":
            return GreedyOptimizer()
        raise ValueError(f"Unknown optimizer: {optimizer}")
    return optimizer
