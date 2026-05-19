"""Shared coverage evaluation helpers for minimizers."""

from dataclasses import dataclass

import numpy as np

from pytest_alchemist.minimizer.models import MinimizationInput

TargetLine = tuple[str, int]


@dataclass(frozen=True)
class CoverageEvaluation:
    """Precomputed changed-line coverage facts for minimization."""

    all_target_lines: tuple[TargetLine, ...]
    coverable_target_lines: tuple[TargetLine, ...]
    coverage_matrix: np.ndarray
    uncovered_target_count: int

    @property
    def target_count(self) -> int:
        """Return the number of changed current-side target lines."""

        return len(self.all_target_lines)

    @property
    def coverable_target_count(self) -> int:
        """Return the number of targets covered by at least one candidate."""

        return len(self.coverable_target_lines)

    def covered_line_count(self, position: np.ndarray) -> int:
        """Return how many current-side changed lines one subset covers."""

        if not self.all_target_lines or not np.any(position):
            return 0

        target_indexes = {
            target: index for index, target in enumerate(self.all_target_lines)
        }
        covered = np.zeros(len(self.all_target_lines), dtype=bool)
        coverable_indexes = [
            target_indexes[target] for target in self.coverable_target_lines
        ]

        if coverable_indexes:
            covered_coverable = np.any(self.coverage_matrix[position], axis=0)
            covered[np.asarray(coverable_indexes)] = covered_coverable

        return int(np.count_nonzero(covered))

    def coverage_percent(self, position: np.ndarray) -> float:
        """Return selected changed-line coverage over all current-side targets."""

        if not self.all_target_lines:
            return 100.0

        return 100.0 * self.covered_line_count(position) / len(self.all_target_lines)


def build_coverage_evaluation(input_data: MinimizationInput) -> CoverageEvaluation:
    """Build the candidate-to-coverable-target coverage matrix."""

    all_target_lines = tuple(
        sorted(
            {
                (change.file_path, line)
                for change in input_data.target_changes
                for line in change.current_lines
            }
        )
    )
    candidate_nodeids = {candidate.nodeid for candidate in input_data.candidates}
    covered_by_candidate: set[TargetLine] = set()
    records_by_test: dict[str, set[TargetLine]] = {
        candidate.nodeid: set() for candidate in input_data.candidates
    }

    all_targets = set(all_target_lines)
    for record in input_data.coverage_records:
        if record.test_nodeid not in candidate_nodeids:
            continue

        covered_targets = {
            (record.file_path, line)
            for line in record.lines
            if (record.file_path, line) in all_targets
        }
        records_by_test[record.test_nodeid].update(covered_targets)
        covered_by_candidate.update(covered_targets)

    coverable_target_lines = tuple(
        target for target in all_target_lines if target in covered_by_candidate
    )
    coverage_matrix = np.zeros(
        (len(input_data.candidates), len(coverable_target_lines)),
        dtype=bool,
    )
    target_indexes = {
        target: index for index, target in enumerate(coverable_target_lines)
    }

    for row_index, candidate in enumerate(input_data.candidates):
        for target in records_by_test[candidate.nodeid]:
            target_index = target_indexes.get(target)
            if target_index is not None:
                coverage_matrix[row_index, target_index] = True

    return CoverageEvaluation(
        all_target_lines=all_target_lines,
        coverable_target_lines=coverable_target_lines,
        coverage_matrix=coverage_matrix,
        uncovered_target_count=len(all_target_lines) - len(coverable_target_lines),
    )
