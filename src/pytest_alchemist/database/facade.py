"""In-memory database facade used until SQLite persistence is implemented."""

from pytest_alchemist.coverage_analysis.models import CoverageRecord
from pytest_alchemist.diff_picker.models import ChangedCode
from pytest_alchemist.test_runner.models import TestCase, TestRunResult


class DatabaseFacade:
    """Small facade that exposes deterministic mock project history."""

    def __init__(self) -> None:
        self._tests = [
            TestCase(
                nodeid="tests/test_math.py::test_add",
                file_path="tests/test_math.py",
                estimated_duration=0.12,
            ),
            TestCase(
                nodeid="tests/test_math.py::test_subtract",
                file_path="tests/test_math.py",
                estimated_duration=0.10,
            ),
            TestCase(
                nodeid="tests/test_api.py::test_create_user",
                file_path="tests/test_api.py",
                estimated_duration=0.35,
            ),
        ]
        self._coverage_records = [
            CoverageRecord(
                test_nodeid="tests/test_math.py::test_add",
                file_path="src/example/math.py",
                lines=[10, 11, 12],
            ),
            CoverageRecord(
                test_nodeid="tests/test_math.py::test_subtract",
                file_path="src/example/math.py",
                lines=[18, 19, 20],
            ),
            CoverageRecord(
                test_nodeid="tests/test_api.py::test_create_user",
                file_path="src/example/api.py",
                lines=[5, 6, 7],
            ),
        ]
        self._coverage_collection_runs: list[list[CoverageRecord]] = []
        self._test_runs: list[TestRunResult] = []

    def list_tests(self) -> list[TestCase]:
        """Return known tests from mock history."""

        return list(self._tests)

    def list_coverage_records(self) -> list[CoverageRecord]:
        """Return known coverage records from mock history."""

        return list(self._coverage_records)

    def get_recent_changes(self, last_commits: int) -> list[ChangedCode]:
        """Return deterministic changed code for a requested commit window."""

        if last_commits <= 1:
            return [ChangedCode(file_path="src/example/math.py", lines=[10, 11])]

        return [
            ChangedCode(file_path="src/example/math.py", lines=[10, 11, 18]),
            ChangedCode(file_path="src/example/api.py", lines=[6]),
        ]

    def save_coverage_collection(self, records: list[CoverageRecord]) -> None:
        """Store collected coverage in memory for the current process."""

        self._coverage_collection_runs.append(list(records))

    def save_test_run(self, result: TestRunResult) -> None:
        """Store a test run result in memory for the current process."""

        self._test_runs.append(result)
