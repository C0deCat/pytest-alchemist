from pathlib import Path

from pytest_alchemist.application import AlchemistApplication
from pytest_alchemist.minimizer import Minimizer
from pytest_alchemist.minimizer.models import MinimizationInput
from pytest_alchemist.test_runner.models import TestCase, TestRunResult


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
    def fake_run_tests(
        project_path: str,
        tests: list[TestCase | str] | None,
        collect_coverage: object,
    ) -> TestRunResult:
        return TestRunResult(
            selected_tests=list(tests or []),
            passed=len(tests or []),
            failed=0,
            duration_seconds=0.01,
            exit_code=0,
        )

    app = AlchemistApplication(run_tests_func=fake_run_tests)

    result = app.run_minimal(last_commits=3)

    assert result.exit_code == 0
    assert result.failed == 0
    assert result.passed == len(result.selected_tests)


def test_application_defaults_project_path_to_cwd() -> None:
    app = AlchemistApplication()

    assert app.project_path == Path.cwd().resolve()


def test_application_accepts_explicit_project_path(tmp_path: Path) -> None:
    app = AlchemistApplication(project_path=tmp_path)

    assert app.project_path == tmp_path.resolve()


def test_run_minimal_passes_project_path_to_runner(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run_tests(
        project_path: str,
        tests: list[TestCase | str] | None,
        collect_coverage: object,
    ) -> TestRunResult:
        captured["project_path"] = project_path
        captured["tests"] = tests
        captured["collect_coverage"] = collect_coverage
        return TestRunResult(
            selected_tests=list(tests or []),
            passed=len(tests or []),
            failed=0,
            duration_seconds=0.01,
            exit_code=0,
        )

    app = AlchemistApplication(project_path=tmp_path, run_tests_func=fake_run_tests)

    result = app.run_minimal(last_commits=3)

    assert captured["project_path"] == str(tmp_path.resolve())
    assert captured["tests"] == result.selected_tests
    assert captured["collect_coverage"] is None


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
