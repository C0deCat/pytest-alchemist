"""Objective evaluation for feasible MOPSO subsets."""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ObjectiveValue:
    """Runtime and selected-test count for one subset."""

    runtime: float
    selected_count: int


def evaluate_position(position: np.ndarray, durations: np.ndarray) -> ObjectiveValue:
    """Return objective values for one binary subset."""

    return ObjectiveValue(
        runtime=float(np.sum(durations[position])),
        selected_count=int(np.count_nonzero(position)),
    )


def evaluate_positions(
    positions: np.ndarray,
    durations: np.ndarray,
) -> list[ObjectiveValue]:
    """Return objective values for many binary subsets."""

    runtimes = positions @ durations
    selected_counts = np.count_nonzero(positions, axis=1)
    return [
        ObjectiveValue(runtime=float(runtime), selected_count=int(selected_count))
        for runtime, selected_count in zip(runtimes, selected_counts, strict=True)
    ]


def prefers(
    left: ObjectiveValue,
    right: ObjectiveValue,
    runtime_tolerance_ms: int,
) -> bool:
    """Return whether one feasible objective is preferred for final selection."""

    tolerance_seconds = runtime_tolerance_ms / 1000.0
    runtime_delta = left.runtime - right.runtime
    if runtime_delta < -tolerance_seconds:
        return True
    if abs(runtime_delta) <= tolerance_seconds:
        if left.selected_count != right.selected_count:
            return left.selected_count < right.selected_count
        return left.runtime < right.runtime
    return False
