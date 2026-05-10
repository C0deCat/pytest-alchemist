from pytest_alchemist.application import AlchemistApplication
from pytest_alchemist.minimizer import Minimizer
from pytest_alchemist.minimizer.models import MinimizationInput
from pytest_alchemist.test_runner.models import TestCase


def test_collect_coverage_returns_mock_summary() -> None:
    app = AlchemistApplication()

    result = app.collect_coverage()

    assert result.records
    assert result.tests
    assert result.covered_files == ["src/example/api.py", "src/example/math.py"]


def test_select_tests_returns_non_empty_minimized_set() -> None:
    app = AlchemistApplication()

    result = app.select_tests(last_commits=3)

    assert result.selected_tests
    assert all(test.nodeid for test in result.selected_tests)


def test_run_minimal_returns_successful_mock_result() -> None:
    app = AlchemistApplication()

    result = app.run_minimal(last_commits=3)

    assert result.exit_code == 0
    assert result.failed == 0
    assert result.passed == len(result.selected_tests)


def test_minimizer_uses_input_data_without_database() -> None:
    minimizer = Minimizer()
    candidate = TestCase(
        nodeid="tests/test_sample.py::test_example",
        file_path="tests/test_sample.py",
        estimated_duration=0.01,
    )

    result = minimizer.minimize(
        MinimizationInput(
            candidates=[candidate],
            target_changes=[],
            coverage_records=[],
        )
    )

    assert result.selected_tests == [candidate]
