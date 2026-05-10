"""Application scenarios for Pytest Alchemist."""

from pytest_alchemist.coverage_analysis.analyzer import CoverageAnalyzer
from pytest_alchemist.coverage_analysis.models import CoverageCollectionResult
from pytest_alchemist.database.facade import DatabaseFacade
from pytest_alchemist.diff_picker.picker import DiffPicker
from pytest_alchemist.minimizer.minimizer import Minimizer
from pytest_alchemist.minimizer.models import MinimizationInput, MinimizationResult
from pytest_alchemist.test_runner.models import TestRunResult
from pytest_alchemist.test_runner.runner import TestRunner


class AlchemistApplication:
    """Coordinates CLI scenarios across infrastructure and algorithms."""

    def __init__(
        self,
        database: DatabaseFacade | None = None,
        coverage_analyzer: CoverageAnalyzer | None = None,
        diff_picker: DiffPicker | None = None,
        minimizer: Minimizer | None = None,
        test_runner: TestRunner | None = None,
    ) -> None:
        self._database = database or DatabaseFacade()
        self._coverage_analyzer = coverage_analyzer or CoverageAnalyzer(self._database)
        self._diff_picker = diff_picker or DiffPicker(self._database)
        self._minimizer = minimizer or Minimizer()
        self._test_runner = test_runner or TestRunner()

    def collect_coverage(self) -> CoverageCollectionResult:
        """Collect and store coverage data."""

        return self._coverage_analyzer.collect()

    def select_tests(self, last_commits: int) -> MinimizationResult:
        """Select a minimized test set for recent changes."""

        selection = self._diff_picker.pick_candidates(last_commits)
        return self._minimizer.minimize(
            MinimizationInput(
                candidates=selection.candidates,
                target_changes=selection.target_changes,
                coverage_records=selection.coverage_records,
            )
        )

    def run_minimal(self, last_commits: int) -> TestRunResult:
        """Select and run a minimized test set."""

        minimization_result = self.select_tests(last_commits)
        run_result = self._test_runner.run_tests(minimization_result.selected_tests)
        self._database.save_test_run(run_result)
        return run_result
