"""Pareto archive utilities for binary MOPSO."""

from dataclasses import dataclass

import numpy as np

from pytest_alchemist.minimizer.mopso.objectives import ObjectiveValue, prefers


@dataclass(frozen=True)
class ArchiveEntry:
    """One feasible subset stored in the Pareto archive."""

    position: np.ndarray
    objective: ObjectiveValue


def dominates(left: ObjectiveValue, right: ObjectiveValue) -> bool:
    """Return whether one minimization objective Pareto-dominates another."""

    no_worse = (
        left.runtime <= right.runtime
        and left.selected_count <= right.selected_count
    )
    strictly_better = (
        left.runtime < right.runtime
        or left.selected_count < right.selected_count
    )
    return no_worse and strictly_better


class ParetoArchive:
    """Deduplicated bounded archive of feasible non-dominated subsets."""

    def __init__(self, max_size: int) -> None:
        self._max_size = max_size
        self._entries: list[ArchiveEntry] = []

    @property
    def entries(self) -> list[ArchiveEntry]:
        """Return archive entries in their current order."""

        return list(self._entries)

    def add(self, position: np.ndarray, objective: ObjectiveValue) -> None:
        """Add one feasible subset if it is not dominated by the archive."""

        copied_position = position.astype(bool, copy=True)
        if any(np.array_equal(entry.position, copied_position) for entry in self._entries):
            return
        if any(dominates(entry.objective, objective) for entry in self._entries):
            return

        self._entries = [
            entry
            for entry in self._entries
            if not dominates(objective, entry.objective)
        ]
        self._entries.append(ArchiveEntry(copied_position, objective))
        self._prune_if_needed()

    def choose_leader(self, rng: np.random.Generator) -> ArchiveEntry:
        """Choose a leader while favoring sparse archive regions."""

        if not self._entries:
            raise ValueError("Cannot choose a leader from an empty archive.")

        distances = _crowding_distances(self._entries)
        if np.all(np.isinf(distances)):
            return self._entries[int(rng.integers(len(self._entries)))]

        finite_values = distances[np.isfinite(distances)]
        replacement = float(finite_values.max() + 1.0) if finite_values.size else 1.0
        weights = np.where(np.isfinite(distances), distances, replacement)
        if np.all(weights == 0):
            return self._entries[int(rng.integers(len(self._entries)))]

        weights = weights / weights.sum()
        index = int(rng.choice(len(self._entries), p=weights))
        return self._entries[index]

    def choose_final(self, runtime_tolerance_ms: int) -> ArchiveEntry:
        """Return the public result selected from the archive."""

        if not self._entries:
            raise ValueError("Cannot choose a final result from an empty archive.")

        chosen = self._entries[0]
        for entry in self._entries[1:]:
            if prefers(entry.objective, chosen.objective, runtime_tolerance_ms):
                chosen = entry
        return chosen

    def _prune_if_needed(self) -> None:
        if len(self._entries) <= self._max_size:
            return

        while len(self._entries) > self._max_size:
            distances = _crowding_distances(self._entries)
            finite_indexes = np.where(np.isfinite(distances))[0]
            if len(finite_indexes) == 0:
                remove_index = len(self._entries) - 1
            else:
                remove_index = int(finite_indexes[np.argmin(distances[finite_indexes])])
            self._entries.pop(remove_index)


def _crowding_distances(entries: list[ArchiveEntry]) -> np.ndarray:
    """Return NSGA-II style crowding distances for archive diversity."""

    distances = np.zeros(len(entries), dtype=float)
    if len(entries) <= 2:
        distances.fill(np.inf)
        return distances

    objectives = np.asarray(
        [[entry.objective.runtime, entry.objective.selected_count] for entry in entries],
        dtype=float,
    )
    for column_index in range(objectives.shape[1]):
        sorted_indexes = np.argsort(objectives[:, column_index])
        distances[sorted_indexes[0]] = np.inf
        distances[sorted_indexes[-1]] = np.inf
        min_value = objectives[sorted_indexes[0], column_index]
        max_value = objectives[sorted_indexes[-1], column_index]
        if max_value == min_value:
            continue
        for offset in range(1, len(sorted_indexes) - 1):
            current_index = sorted_indexes[offset]
            if np.isinf(distances[current_index]):
                continue
            previous_value = objectives[sorted_indexes[offset - 1], column_index]
            next_value = objectives[sorted_indexes[offset + 1], column_index]
            distances[current_index] += (next_value - previous_value) / (
                max_value - min_value
            )
    return distances
