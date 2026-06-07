import json
from pathlib import Path

from pytest_alchemist.test_runner.models import TestCase
from pytest_alchemist.test_runner.runner import ARTIFACTS_DIR_NAME, TestRunner


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


def _create_mixed_pytest_project(project_path: Path) -> None:
    tests_path = project_path / "tests"
    tests_path.mkdir()
    (tests_path / "test_sample.py").write_text(
        "\n".join(
            [
                "import pytest",
                "",
                "def test_passes():",
                "    assert True",
                "",
                "def test_fails():",
                "    assert False",
                "",
                "def test_skips():",
                "    pytest.skip('not today')",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _read_report(test_report_path: str) -> dict:
    return json.loads(Path(test_report_path).read_text(encoding="utf-8"))


def test_run_tests_runs_all_tests(tmp_path: Path) -> None:
    _create_pytest_project(tmp_path)

    test_report_path = TestRunner().run_tests(str(tmp_path))
    report = _read_report(test_report_path)

    assert Path(test_report_path).exists()
    assert report["exit_code"] == 0
    assert report["summary"]["passed"] == 2
    assert report["summary"]["failed"] == 0
    assert report["pytest"]["stdout_path"] is not None
    assert report["pytest"]["stderr_path"] is not None
    assert Path(report["pytest"]["stdout_path"]).exists()
    assert Path(report["pytest"]["stderr_path"]).exists()
    assert report["uid"]
    assert Path(report["pytest"]["stdout_path"]).parent.name == report["uid"]
    assert report["project_root"] == str(tmp_path.resolve())
    assert report["started_at"]
    assert report["finished_at"]
    assert report["pytest"]["args"]
    assert ARTIFACTS_DIR_NAME in Path(report["pytest"]["stdout_path"]).parts
    assert not list(Path(report["artifacts"]["run_dir"]).glob("*plugin*.py"))


def test_run_tests_runs_selected_nodeid(tmp_path: Path) -> None:
    _create_pytest_project(tmp_path)

    test_report_path = TestRunner().run_tests(
        str(tmp_path),
        ["tests/test_sample.py::test_one"],
    )
    report = _read_report(test_report_path)

    assert report["exit_code"] == 0
    assert report["summary"]["passed"] == 1
    assert report["summary"]["failed"] == 0
    assert report["selection"]["selected_tests"] == ["tests/test_sample.py::test_one"]


def test_run_tests_accepts_test_case(tmp_path: Path) -> None:
    _create_pytest_project(tmp_path)
    test_case = TestCase(
        nodeid="tests/test_sample.py::test_two",
        file_path="tests/test_sample.py",
        estimated_duration=0.01,
    )

    test_report_path = TestRunner().run_tests(str(tmp_path), [test_case])
    report = _read_report(test_report_path)

    assert report["exit_code"] == 0
    assert report["summary"]["passed"] == 1
    assert report["selection"]["selected_tests"] == [test_case.nodeid]


def test_run_tests_treats_empty_selection_as_noop(tmp_path: Path) -> None:
    _create_pytest_project(tmp_path)

    test_report_path = TestRunner().run_tests(str(tmp_path), [])
    report = _read_report(test_report_path)

    assert report["exit_code"] == 0
    assert report["summary"] == {
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "total": 0,
    }
    assert report["selection"]["selected_tests"] == []
    assert report["runned_tests"] == {}
    assert Path(report["pytest"]["stdout_path"]).read_text(encoding="utf-8") == (
        "No tests selected.\n"
    )


def test_run_tests_collects_json_coverage(tmp_path: Path) -> None:
    _create_pytest_project(tmp_path)

    test_report_path = TestRunner().run_tests(str(tmp_path), collect_coverage="json")
    report = _read_report(test_report_path)

    assert report["exit_code"] == 0
    assert report["coverage"] is not None
    assert report["coverage"]["format"] == "json"
    assert report["coverage"]["coverage_json_path"] is not None
    assert report["coverage"]["coverage_xml_path"] is None
    assert report["coverage"]["coverage_sqlite_path"] is not None
    assert Path(report["coverage"]["coverage_json_path"]).exists()
    assert Path(report["coverage"]["coverage_sqlite_path"]).exists()
    assert "--cov-context=test" in report["pytest"]["args"]
    assert "--cov-branch" in report["pytest"]["args"]


def test_run_tests_collects_xml_coverage(tmp_path: Path) -> None:
    _create_pytest_project(tmp_path)

    test_report_path = TestRunner().run_tests(str(tmp_path), collect_coverage="xml")
    report = _read_report(test_report_path)

    assert report["exit_code"] == 0
    assert report["coverage"] is not None
    assert report["coverage"]["format"] == "xml"
    assert report["coverage"]["coverage_xml_path"] is not None
    assert report["coverage"]["coverage_json_path"] is None
    assert report["coverage"]["coverage_sqlite_path"] is not None
    assert Path(report["coverage"]["coverage_xml_path"]).exists()
    assert Path(report["coverage"]["coverage_sqlite_path"]).exists()


def test_run_tests_collects_sqlite_coverage(tmp_path: Path) -> None:
    _create_pytest_project(tmp_path)

    test_report_path = TestRunner().run_tests(str(tmp_path), collect_coverage="sqlite")
    report = _read_report(test_report_path)

    assert report["exit_code"] == 0
    assert report["coverage"] is not None
    assert report["coverage"]["format"] == "sqlite"
    assert report["coverage"]["coverage_json_path"] is None
    assert report["coverage"]["coverage_xml_path"] is None
    assert report["coverage"]["coverage_sqlite_path"] is not None
    assert Path(report["coverage"]["coverage_sqlite_path"]).exists()
    assert any(arg.startswith("--cov") for arg in report["pytest"]["args"])
    assert "--cov-context=test" in report["pytest"]["args"]
    assert "--cov-branch" in report["pytest"]["args"]
    assert "--cov-report=" in report["pytest"]["args"]


def test_run_tests_collects_per_test_results(tmp_path: Path) -> None:
    _create_mixed_pytest_project(tmp_path)

    test_report_path = TestRunner().run_tests(str(tmp_path))
    report = _read_report(test_report_path)

    assert report["exit_code"] == 1
    assert report["summary"] == {
        "passed": 1,
        "failed": 1,
        "skipped": 1,
        "total": 3,
    }
    assert report["runned_tests"]["tests/test_sample.py::test_passes"]["outcome"] == "passed"
    assert report["runned_tests"]["tests/test_sample.py::test_fails"]["outcome"] == "failed"
    assert report["runned_tests"]["tests/test_sample.py::test_skips"]["outcome"] == "skipped"
    assert all(
        isinstance(test_result["duration_ms"], int)
        for test_result in report["runned_tests"].values()
    )


def test_run_tests_can_skip_per_test_collection(tmp_path: Path) -> None:
    _create_pytest_project(tmp_path)

    test_report_path = TestRunner().run_tests(str(tmp_path), collects_tests=False)
    report = _read_report(test_report_path)

    assert report["exit_code"] == 0
    assert report["summary"]["passed"] == 2
    assert report["runned_tests"] == {}


def test_run_tests_writes_utf8_subprocess_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    tests_path = tmp_path / "tests"
    tests_path.mkdir()
    (tests_path / "test_unicode.py").write_text(
        "\n".join(
            [
                "def test_unicode_output():",
                "    print('pytest says 😇')",
                "    assert False",
                "",
            ]
        ),
        encoding="utf-8",
    )

    test_report_path = TestRunner().run_tests(
        str(tmp_path),
        ["tests/test_unicode.py::test_unicode_output"],
    )
    report = _read_report(test_report_path)
    stdout = Path(report["pytest"]["stdout_path"]).read_text(encoding="utf-8")

    assert report["exit_code"] == 1
    assert "pytest says 😇" in stdout
