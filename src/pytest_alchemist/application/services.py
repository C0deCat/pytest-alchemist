"""Application scenarios for Pytest Alchemist."""

from pathlib import Path
from typing import Callable

from pytest_alchemist.coverage_analysis.analyzer import CoverageAnalyzer
from pytest_alchemist.coverage_analysis.models import CoverageCollectionResult
from pytest_alchemist.database.facade import DatabaseFacade
from pytest_alchemist.diff_picker.models import TestSelection
from pytest_alchemist.diff_picker.picker import DiffPicker
from pytest_alchemist.application.models import (
    GitSnapshot,
    MinimizerComparison,
    MinimizerComparisonEntry,
    ProjectStatus,
)
from pytest_alchemist.minimizer.interface import MinimizerInterface
from pytest_alchemist.minimizer.minimizer import Minimizer
from pytest_alchemist.minimizer.models import MinimizationInput
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
        minimizer: MinimizerInterface | None = None,
        run_tests_func: RunTestsFunc | None = None,
    ) -> None:
        self.project_path = Path(project_path or Path.cwd()).resolve()
        self._database = database or DatabaseFacade(self.project_path)
        self._coverage_analyzer = coverage_analyzer or CoverageAnalyzer(self._database)
        self._diff_picker = diff_picker or DiffPicker(self._database)
        self._minimizer = minimizer or Minimizer()
        self._run_tests = run_tests_func or TestRunner().run_tests

    def get_project_status(self) -> ProjectStatus:
        """Return dashboard-ready state for the target project."""

        coverage = self._database.get_latest_coverage_status()
        latest_run = self._database.get_latest_test_run_status()
        counts = self._database.get_dashboard_counts()
        git_branch = coverage["git_branch"] if coverage else None
        git_commit = coverage["git_commit"] if coverage else None
        git_is_dirty = coverage["git_is_dirty"] if coverage else None

        return ProjectStatus(
            project_path=self.project_path,
            latest_coverage_run_uid=coverage["run_uid"] if coverage else None,
            latest_coverage_created_at=coverage["created_at"] if coverage else None,
            latest_coverage_quality=coverage["quality"] if coverage else None,
            latest_run_uid=latest_run["uid"] if latest_run else None,
            latest_run_finished_at=latest_run["finished_at"] if latest_run else None,
            latest_run_status=latest_run["status"] if latest_run else None,
            coverage_entity_count=counts["coverage_entity_count"],
            coverage_line_fact_count=counts["coverage_line_fact_count"],
            coverage_arc_fact_count=counts["coverage_arc_fact_count"],
            known_test_count=counts["known_test_count"],
            git=GitSnapshot(
                branch=git_branch,
                commit=git_commit,
                is_dirty=None if git_is_dirty is None else bool(git_is_dirty),
            ),
        )

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

    def select_tests(
        self,
        last_commits: int | None = None,
        commit_hash: str | None = None,
    ) -> TestSelection:
        """Select the full affected test set for recent or explicit changes."""

        return self._diff_picker.pick_candidates(
            last_commits=last_commits,
            commit_hash=commit_hash,
        )

    def run_minimal(
        self,
        last_commits: int | None = None,
        commit_hash: str | None = None,
        seed: int | None = None,
        runtime_tolerance_ms: int = 10,
    ) -> str:
        """Select and run a minimized test set."""

        selection = self.select_tests(last_commits=last_commits, commit_hash=commit_hash)
        minimization_result = self._minimizer.minimize(
            MinimizationInput(
                candidates=selection.candidates,
                target_changes=selection.target_changes,
                coverage_records=selection.coverage_records,
            ),
            seed=seed,
            runtime_tolerance_ms=runtime_tolerance_ms,
        )
        test_report_path = self._run_tests(
            str(self.project_path),
            minimization_result.selected_tests,
            None,
            True,
        )
        self._database.save_test_run(test_report_path)
        return test_report_path

    def compare_minimizers(
        self,
        last_commits: int | None = None,
        commit_hash: str | None = None,
        seed: int | None = None,
        runtime_tolerance_ms: int = 10,
    ) -> MinimizerComparison:
        """Compare greedy and MOPSO minimizers without running tests."""

        selection = self.select_tests(last_commits=last_commits, commit_hash=commit_hash)
        input_data = MinimizationInput(
            candidates=selection.candidates,
            target_changes=selection.target_changes,
            coverage_records=selection.coverage_records,
        )
        return MinimizerComparison(
            entries=[
                MinimizerComparisonEntry(
                    optimizer_name="Greedy",
                    result=Minimizer("greedy").minimize(
                        input_data,
                        seed=seed,
                        runtime_tolerance_ms=runtime_tolerance_ms,
                    ),
                ),
                MinimizerComparisonEntry(
                    optimizer_name="MOPSO",
                    result=Minimizer("mopso").minimize(
                        input_data,
                        seed=seed,
                        runtime_tolerance_ms=runtime_tolerance_ms,
                    ),
                ),
            ]
        )

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
