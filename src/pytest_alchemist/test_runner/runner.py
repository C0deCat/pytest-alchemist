"""Mock test runner."""

from pytest_alchemist.test_runner.models import TestCase, TestRunResult


class TestRunner:
    """Runs selected tests.

    The initial implementation does not invoke pytest; it returns a deterministic
    successful result for the selected test set.
    """

    def run_tests(self, tests: list[TestCase]) -> TestRunResult:
        """Return a successful mock run result."""

        duration = sum(test.estimated_duration for test in tests)
        return TestRunResult(
            selected_tests=list(tests),
            passed=len(tests),
            failed=0,
            duration_seconds=round(duration, 3),
            exit_code=0,
        )
