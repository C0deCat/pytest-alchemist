"""Deterministic greedy minimizer optimizer."""

import numpy as np

from pytest_alchemist.minimizer.evaluators import CoverageEvaluation
from pytest_alchemist.minimizer.models import MinimizationInput, MinimizationResult
from pytest_alchemist.minimizer.mopso.objectives import evaluate_position
from pytest_alchemist.minimizer.mopso.repair import is_feasible


class GreedyOptimizer:
    """Select tests by greedily covering currently uncovered changed lines."""

    def minimize(
        self,
        input_data: MinimizationInput,
        evaluation: CoverageEvaluation,
        seed: int | None = None,
        runtime_tolerance_ms: int = 10,
    ) -> MinimizationResult:
        """Run deterministic greedy minimization."""

        if runtime_tolerance_ms < 0:
            raise ValueError("runtime_tolerance_ms must be non-negative.")

        position = np.zeros(len(input_data.candidates), dtype=bool)

        if evaluation.coverable_target_count == 0:
            return _build_result(
                input_data=input_data,
                evaluation=evaluation,
                position=position,
                seed=seed or 0,
                reason="No coverable changed current-side lines found.",
            )

        while not is_feasible(position, evaluation.coverage_matrix):
            covered = (
                np.any(evaluation.coverage_matrix[position], axis=0)
                if np.any(position)
                else np.zeros(evaluation.coverage_matrix.shape[1], dtype=bool)
            )
            uncovered = ~covered
            best_index: int | None = None
            best_gain = 0

            for index in range(len(input_data.candidates)):
                if position[index]:
                    continue

                marginal_gain = int(
                    np.count_nonzero(evaluation.coverage_matrix[index] & uncovered)
                )
                if marginal_gain > best_gain:
                    best_index = index
                    best_gain = marginal_gain

            if best_index is None:
                break
            position[best_index] = True

        return _build_result(
            input_data=input_data,
            evaluation=evaluation,
            position=position,
            seed=seed or 0,
            reason="Greedy optimizer selected a feasible subset covering all coverable changed lines.",
        )


def _build_result(
    input_data: MinimizationInput,
    evaluation: CoverageEvaluation,
    position: np.ndarray,
    seed: int,
    reason: str,
) -> MinimizationResult:
    durations = np.asarray(
        [candidate.estimated_duration for candidate in input_data.candidates],
        dtype=float,
    )
    objective = evaluate_position(position, durations)
    selected_tests = [
        candidate
        for candidate, selected in zip(input_data.candidates, position, strict=True)
        if selected
    ]
    return MinimizationResult(
        selected_tests=selected_tests,
        reason=reason,
        coverage_percent=evaluation.coverage_percent(position),
        uncovered_target_count=evaluation.uncovered_target_count,
        selected_test_count=objective.selected_count,
        estimated_runtime=objective.runtime,
        seed=seed,
    )
