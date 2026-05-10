"""Mock deterministic minimizer."""

from pytest_alchemist.minimizer.models import MinimizationInput, MinimizationResult


class Minimizer:
    """Selects a minimal test subset from already prepared input data."""

    def minimize(self, input_data: MinimizationInput) -> MinimizationResult:
        """Select tests by shortest estimated duration until each changed file is covered."""

        if not input_data.candidates:
            return MinimizationResult(selected_tests=[], reason="No candidate tests found.")

        target_files = {change.file_path for change in input_data.target_changes}
        selected = []
        covered_files: set[str] = set()

        for candidate in sorted(
            input_data.candidates, key=lambda test: (test.estimated_duration, test.nodeid)
        ):
            candidate_files = {
                record.file_path
                for record in input_data.coverage_records
                if record.test_nodeid == candidate.nodeid
            }
            if candidate_files.intersection(target_files - covered_files):
                selected.append(candidate)
                covered_files.update(candidate_files)

            if target_files.issubset(covered_files):
                break

        if not selected:
            selected = [input_data.candidates[0]]

        return MinimizationResult(
            selected_tests=selected,
            reason="Mock minimizer selected candidates covering changed files.",
        )
