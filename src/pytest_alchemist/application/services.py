"""Application scenarios for Pytest Alchemist."""

from pathlib import Path
from typing import Callable

from pytest_alchemist.coverage_analysis.analyzer import CoverageAnalyzer
from pytest_alchemist.coverage_analysis.models import CoverageCollectionResult
from pytest_alchemist.database.facade import DatabaseFacade
from pytest_alchemist.diff_picker.picker import DiffPicker
from pytest_alchemist.minimizer.minimizer import Minimizer
from pytest_alchemist.minimizer.models import MinimizationInput, MinimizationResult
from pytest_alchemist.test_runner.models import TestCase
from pytest_alchemist.test_runner.runner import CoverageFormat, TestRunner

RunTestsFunc = Callable[
    [str, list[TestCase | str] | None, CoverageFormat | None, bool],
    str,
]


class AlchemistApplication:
    """Coordinates CLI scenarios across infrastructure and algorithms."""

    def __init__(
        self,
        project_path: str | Path | None = None,
        database: DatabaseFacade | None = None,
        coverage_analyzer: CoverageAnalyzer | None = None,
        diff_picker: DiffPicker | None = None,
        minimizer: Minimizer | None = None,
        run_tests_func: RunTestsFunc | None = None,
    ) -> None:
        self.project_path = Path(project_path or Path.cwd()).resolve()
        self._database = database or DatabaseFacade(self.project_path)
        self._coverage_analyzer = coverage_analyzer or CoverageAnalyzer(self._database)
        self._diff_picker = diff_picker or DiffPicker(self._database)
        self._minimizer = minimizer or Minimizer()
        self._run_tests = run_tests_func or TestRunner().run_tests

    def collect_coverage(self) -> CoverageCollectionResult:
        """Collect and store coverage data."""

        test_report_path = self._run_tests(
            str(self.project_path),
            None,
            "sqlite",
            True,
        )
        self._database.save_test_run(test_report_path)
        return self._coverage_analyzer.collect_from_report(test_report_path)

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

    def run_minimal(self, last_commits: int) -> str:
        """Select and run a minimized test set."""

        minimization_result = self.select_tests(last_commits)
        test_report_path = self._run_tests(
            str(self.project_path),
            minimization_result.selected_tests,
            None,
            True,
        )
        self._database.save_test_run(test_report_path)
        return test_report_path

    def run_tests(
        self,
        tests: list[str] | None = None,
        collect_coverage: CoverageFormat | None = None,
        collects_tests: bool = True,
    ) -> str:
        """Run a requested test set in the target project."""

        test_report_path = self._run_tests(
            str(self.project_path),
            tests,
            collect_coverage,
            collects_tests,
        )
        self._database.save_test_run(test_report_path)
        return test_report_path
