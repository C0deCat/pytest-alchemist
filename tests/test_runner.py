from pathlib import Path

from pytest_alchemist.test_runner.models import TestCase
from pytest_alchemist.test_runner.runner import ARTIFACTS_DIR_NAME, run_tests


def _create_pytest_project(project_path: Path) -> None:
    tests_path = project_path / "tests"
    tests_path.mkdir()
    (tests_path / "test_sample.py").write_text(
        "\n".join(
            [
                "def test_one():",
                "    assert True",
                "",
                "def test_two():",
                "    assert True",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_run_tests_runs_all_tests(tmp_path: Path) -> None:
    _create_pytest_project(tmp_path)

    result = run_tests(str(tmp_path))

    assert result.exit_code == 0
    assert result.passed == 2
    assert result.failed == 0
    assert result.stdout_path is not None
    assert result.stderr_path is not None
    assert Path(result.stdout_path).exists()
    assert Path(result.stderr_path).exists()
    assert ARTIFACTS_DIR_NAME in Path(result.stdout_path).parts


def test_run_tests_runs_selected_nodeid(tmp_path: Path) -> None:
    _create_pytest_project(tmp_path)

    result = run_tests(str(tmp_path), ["tests/test_sample.py::test_one"])

    assert result.exit_code == 0
    assert result.passed == 1
    assert result.failed == 0
    assert result.selected_tests == ["tests/test_sample.py::test_one"]


def test_run_tests_accepts_test_case(tmp_path: Path) -> None:
    _create_pytest_project(tmp_path)
    test_case = TestCase(
        nodeid="tests/test_sample.py::test_two",
        file_path="tests/test_sample.py",
        estimated_duration=0.01,
    )

    result = run_tests(str(tmp_path), [test_case])

    assert result.exit_code == 0
    assert result.passed == 1
    assert result.selected_tests == [test_case]


def test_run_tests_collects_json_coverage(tmp_path: Path) -> None:
    _create_pytest_project(tmp_path)

    result = run_tests(str(tmp_path), collect_coverage="json")

    assert result.exit_code == 0
    assert result.coverage is not None
    assert result.coverage.coverage_json_path is not None
    assert result.coverage.coverage_xml_path is None
    assert Path(result.coverage.coverage_json_path).exists()


def test_run_tests_collects_xml_coverage(tmp_path: Path) -> None:
    _create_pytest_project(tmp_path)

    result = run_tests(str(tmp_path), collect_coverage="xml")

    assert result.exit_code == 0
    assert result.coverage is not None
    assert result.coverage.coverage_xml_path is not None
    assert result.coverage.coverage_json_path is None
    assert Path(result.coverage.coverage_xml_path).exists()
