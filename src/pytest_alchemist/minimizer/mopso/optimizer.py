"""Binary Multi-Objective Particle Swarm Optimization minimizer."""

from dataclasses import dataclass
import secrets

import numpy as np

from pytest_alchemist.minimizer.evaluators import CoverageEvaluation
from pytest_alchemist.minimizer.models import MinimizationInput, MinimizationResult
from pytest_alchemist.minimizer.mopso.archive import ParetoArchive
from pytest_alchemist.minimizer.mopso.objectives import (
    ObjectiveValue,
    evaluate_position,
    evaluate_positions,
    prefers,
)
from pytest_alchemist.minimizer.mopso.repair import (
    is_feasible,
    prune_position,
    repair_position,
)


@dataclass(frozen=True)
class MOPSOConfig:
    """Internal search configuration for the default optimizer."""

    particle_count: int = 24
    iteration_count: int = 60
    inertia_start: float = 0.9
    inertia_end: float = 0.4
    cognitive_weight: float = 1.5
    social_weight: float = 1.5
    velocity_min: float = -4.0
    velocity_max: float = 4.0
    mutation_probability_start: float = 0.08
    mutation_probability_end: float = 0.01
    archive_size_limit: int = 64


DEFAULT_CONFIG = MOPSOConfig()


class MOPSOOptimizer:
    """Concrete binary MOPSO minimizer."""

    def __init__(self, config: MOPSOConfig = DEFAULT_CONFIG) -> None:
        self._config = config

    def minimize(
        self,
        input_data: MinimizationInput,
        evaluation: CoverageEvaluation,
        seed: int | None = None,
        runtime_tolerance_ms: int = 10,
    ) -> MinimizationResult:
        """Run the optimizer and return one selected feasible subset."""

        if runtime_tolerance_ms < 0:
            raise ValueError("runtime_tolerance_ms must be non-negative.")

        seed_used = int(seed if seed is not None else secrets.randbits(63))
        rng = np.random.default_rng(seed_used)
        durations = np.asarray(
            [candidate.estimated_duration for candidate in input_data.candidates],
            dtype=float,
        )

        if evaluation.coverable_target_count == 0:
            empty_position = np.zeros(len(input_data.candidates), dtype=bool)
            return _build_result(
                input_data=input_data,
                evaluation=evaluation,
                position=empty_position,
                objective=ObjectiveValue(runtime=0.0, selected_count=0),
                seed=seed_used,
                reason="No coverable changed current-side lines found.",
            )

        positions = rng.random(
            (self._config.particle_count, len(input_data.candidates))
        ) < 0.5
        velocities = rng.uniform(
            low=self._config.velocity_min,
            high=self._config.velocity_max,
            size=positions.shape,
        )
        positions = self._repair_and_prune_many(
            positions,
            evaluation.coverage_matrix,
            durations,
        )

        objectives = evaluate_positions(positions, durations)
        personal_best_positions = positions.copy()
        personal_best_objectives = list(objectives)
        archive = ParetoArchive(max_size=self._config.archive_size_limit)
        for position, objective in zip(positions, objectives, strict=True):
            if is_feasible(position, evaluation.coverage_matrix):
                archive.add(position, objective)

        for iteration in range(self._config.iteration_count):
            inertia = _linear_schedule(
                self._config.inertia_start,
                self._config.inertia_end,
                iteration,
                self._config.iteration_count,
            )
            mutation_probability = _linear_schedule(
                self._config.mutation_probability_start,
                self._config.mutation_probability_end,
                iteration,
                self._config.iteration_count,
            )

            for particle_index in range(len(positions)):
                leader = archive.choose_leader(rng)
                current = positions[particle_index].astype(float)
                personal_best = personal_best_positions[particle_index].astype(float)
                leader_position = leader.position.astype(float)
                cognitive_random = rng.random(len(current))
                social_random = rng.random(len(current))
                velocities[particle_index] = (
                    inertia * velocities[particle_index]
                    + self._config.cognitive_weight
                    * cognitive_random
                    * (personal_best - current)
                    + self._config.social_weight
                    * social_random
                    * (leader_position - current)
                )
                velocities[particle_index] = np.clip(
                    velocities[particle_index],
                    self._config.velocity_min,
                    self._config.velocity_max,
                )
                probabilities = _sigmoid(velocities[particle_index])
                positions[particle_index] = rng.random(len(current)) < probabilities
                mutation_mask = rng.random(len(current)) < mutation_probability
                positions[particle_index] = np.logical_xor(
                    positions[particle_index],
                    mutation_mask,
                )

            positions = self._repair_and_prune_many(
                positions,
                evaluation.coverage_matrix,
                durations,
            )
            objectives = evaluate_positions(positions, durations)

            for particle_index, objective in enumerate(objectives):
                if prefers(
                    objective,
                    personal_best_objectives[particle_index],
                    runtime_tolerance_ms,
                ):
                    personal_best_positions[particle_index] = positions[particle_index]
                    personal_best_objectives[particle_index] = objective
                archive.add(positions[particle_index], objective)

        chosen = archive.choose_final(runtime_tolerance_ms)
        return _build_result(
            input_data=input_data,
            evaluation=evaluation,
            position=chosen.position,
            objective=chosen.objective,
            seed=seed_used,
            reason="Binary MOPSO selected a feasible subset covering all coverable changed lines.",
        )

    @staticmethod
    def _repair_and_prune_many(
        positions: np.ndarray,
        coverage_matrix: np.ndarray,
        durations: np.ndarray,
    ) -> np.ndarray:
        repaired_positions = []
        for position in positions:
            repaired = repair_position(position, coverage_matrix, durations)
            repaired_positions.append(prune_position(repaired, coverage_matrix, durations))
        return np.asarray(repaired_positions, dtype=bool)


def _build_result(
    input_data: MinimizationInput,
    evaluation: CoverageEvaluation,
    position: np.ndarray,
    objective: ObjectiveValue,
    seed: int,
    reason: str,
) -> MinimizationResult:
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


def _linear_schedule(start: float, end: float, iteration: int, total: int) -> float:
    if total <= 1:
        return end
    progress = iteration / (total - 1)
    return start + (end - start) * progress


def _sigmoid(values: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-values))
