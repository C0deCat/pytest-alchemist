"""Repair and prune operators for binary MOPSO subsets."""

import numpy as np


def is_feasible(position: np.ndarray, coverage_matrix: np.ndarray) -> bool:
    """Return whether one subset covers every coverable target."""

    if coverage_matrix.shape[1] == 0:
        return True
    if not np.any(position):
        return False
    return bool(np.all(np.any(coverage_matrix[position], axis=0)))


def repair_position(
    position: np.ndarray,
    coverage_matrix: np.ndarray,
    durations: np.ndarray,
) -> np.ndarray:
    """Add tests greedily until every coverable target is covered."""

    repaired = position.astype(bool, copy=True)
    if coverage_matrix.shape[1] == 0:
        return repaired

    while not is_feasible(repaired, coverage_matrix):
        covered = (
            np.any(coverage_matrix[repaired], axis=0)
            if np.any(repaired)
            else np.zeros(coverage_matrix.shape[1], dtype=bool)
        )
        uncovered = ~covered
        best_index: int | None = None
        best_key: tuple[float, int, float, int] | None = None

        for index in np.where(~repaired)[0]:
            marginal_gain = int(np.count_nonzero(coverage_matrix[index] & uncovered))
            if marginal_gain == 0:
                continue
            duration = float(durations[index])
            ratio = marginal_gain / duration if duration > 0 else float("inf")
            key = (ratio, marginal_gain, -duration, -int(index))
            if best_key is None or key > best_key:
                best_index = int(index)
                best_key = key

        if best_index is None:
            break
        repaired[best_index] = True

    return repaired


def prune_position(
    position: np.ndarray,
    coverage_matrix: np.ndarray,
    durations: np.ndarray,
) -> np.ndarray:
    """Remove redundant selected tests while preserving feasibility."""

    pruned = position.astype(bool, copy=True)
    selected_indexes = np.where(pruned)[0]
    ordered_indexes = sorted(
        (int(index) for index in selected_indexes),
        key=lambda index: (-float(durations[index]), -index),
    )
    for index in ordered_indexes:
        candidate = pruned.copy()
        candidate[index] = False
        if is_feasible(candidate, coverage_matrix):
            pruned = candidate
    return pruned
