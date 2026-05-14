import hashlib
import json
import sqlite3
from pathlib import Path

from pytest_alchemist.database.facade import DATABASE_FILE_NAME, DatabaseFacade
from pytest_alchemist.test_runner.runner import ARTIFACTS_DIR_NAME


def _write_test_report(
    project_path: Path,
    *,
    uid: str = "run-1",
    coverage: dict | None = None,
    runned_tests: dict | None = None,
) -> Path:
    run_dir = project_path / ARTIFACTS_DIR_NAME / "test-runs" / uid
    run_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = run_dir / "stdout.txt"
    stderr_path = run_dir / "stderr.txt"
    stdout_path.write_text("", encoding="utf-8")
    stderr_path.write_text("", encoding="utf-8")
    test_results = runned_tests or {}
    summary = {
        "passed": sum(1 for test in test_results.values() if test["outcome"] == "passed"),
        "failed": sum(1 for test in test_results.values() if test["outcome"] == "failed"),
        "skipped": sum(1 for test in test_results.values() if test["outcome"] == "skipped"),
        "total": len(test_results),
    }
    report_path = run_dir / "test_report.json"
    report = {
        "schema_version": 1,
        "uid": uid,
        "project_root": str(project_path),
        "started_at": "2026-05-13T01:00:00Z",
        "finished_at": "2026-05-13T01:00:01Z",
        "duration_seconds": 1.234,
        "exit_code": 0,
        "status": "passed",
        "pytest": {
            "args": ["python", "-m", "pytest", "tests/test_sample.py::test_one"],
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        },
        "selection": {
            "selected_tests": ["tests/test_sample.py::test_one"],
        },
        "summary": summary,
        "runned_tests": test_results,
        "coverage": coverage,
        "artifacts": {
            "run_dir": str(run_dir),
            "test_report_path": str(report_path),
        },
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return report_path


def test_database_facade_creates_sqlite_schema(tmp_path: Path) -> None:
    database = DatabaseFacade(project_path=tmp_path)

    assert database.database_path == tmp_path / ARTIFACTS_DIR_NAME / DATABASE_FILE_NAME
    assert database.database_path.exists()

    with sqlite3.connect(database.database_path) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert {
        "test_runs",
        "tests",
        "test_results",
        "coverage_artifacts",
    }.issubset(table_names)


def test_save_test_run_persists_run_without_coverage(tmp_path: Path) -> None:
    database = DatabaseFacade(project_path=tmp_path)
    report_path = _write_test_report(
        tmp_path,
        runned_tests={
            "tests/test_sample.py::test_one": {
                "nodeid": "tests/test_sample.py::test_one",
                "outcome": "passed",
                "duration_ms": 42,
            },
        },
    )

    database.save_test_run(report_path)

    with sqlite3.connect(database.database_path) as connection:
        connection.row_factory = sqlite3.Row
        run = connection.execute("SELECT * FROM test_runs WHERE uid = ?", ("run-1",)).fetchone()
        artifacts = connection.execute("SELECT * FROM coverage_artifacts").fetchall()

    assert run is not None
    assert run["status"] == "passed"
    assert run["coverage_enabled"] == 0
    assert run["duration_ms"] == 1234
    assert json.loads(run["selected_nodeids_json"]) == ["tests/test_sample.py::test_one"]
    assert run["stdout_path"] == str(report_path.parent / "stdout.txt")
    assert run["stderr_path"] == str(report_path.parent / "stderr.txt")
    assert json.loads(run["pytest_args_json"]) == [
        "python",
        "-m",
        "pytest",
        "tests/test_sample.py::test_one",
    ]
    assert artifacts == []


def test_save_test_run_persists_coverage_artifact(tmp_path: Path) -> None:
    database = DatabaseFacade(project_path=tmp_path)
    run_dir = tmp_path / ARTIFACTS_DIR_NAME / "test-runs" / "run-coverage"
    run_dir.mkdir(parents=True)
    coverage_json_path = run_dir / "coverage.json"
    coverage_xml_path = run_dir / "coverage.xml"
    coverage_json_path.write_text('{"meta": {}}', encoding="utf-8")
    coverage_xml_path.write_text("<coverage />", encoding="utf-8")
    report_path = _write_test_report(
        tmp_path,
        uid="run-coverage",
        coverage={
            "format": "json",
            "coverage_json_path": str(coverage_json_path),
            "coverage_xml_path": str(coverage_xml_path),
        },
    )

    database.save_test_run(report_path)

    with sqlite3.connect(database.database_path) as connection:
        connection.row_factory = sqlite3.Row
        run = connection.execute(
            "SELECT coverage_enabled, selected_nodeids_json FROM test_runs WHERE uid = ?",
            ("run-coverage",),
        ).fetchone()
        artifacts = connection.execute(
            "SELECT run_uid, format, path, sha256 FROM coverage_artifacts"
        ).fetchall()

    assert run["coverage_enabled"] == 1
    assert json.loads(run["selected_nodeids_json"]) == ["tests/test_sample.py::test_one"]
    artifacts_by_format = {artifact["format"]: artifact for artifact in artifacts}
    assert set(artifacts_by_format) == {"json", "xml"}
    assert artifacts_by_format["json"]["run_uid"] == "run-coverage"
    assert artifacts_by_format["json"]["path"] == str(coverage_json_path)
    assert artifacts_by_format["json"]["sha256"] == hashlib.sha256(
        coverage_json_path.read_bytes()
    ).hexdigest()
    assert artifacts_by_format["xml"]["run_uid"] == "run-coverage"
    assert artifacts_by_format["xml"]["path"] == str(coverage_xml_path)
    assert artifacts_by_format["xml"]["sha256"] == hashlib.sha256(
        coverage_xml_path.read_bytes()
    ).hexdigest()


def test_save_test_run_upserts_tests_and_results(tmp_path: Path) -> None:
    database = DatabaseFacade(project_path=tmp_path)
    report_path = _write_test_report(
        tmp_path,
        uid="run-tests",
        runned_tests={
            "tests/test_sample.py::test_one": {
                "nodeid": "tests/test_sample.py::test_one",
                "outcome": "passed",
                "duration_ms": 250,
            },
            "tests/test_sample.py::test_two": {
                "nodeid": "tests/test_sample.py::test_two",
                "outcome": "failed",
                "duration_ms": 125,
            },
        },
    )

    database.save_test_run(report_path)

    with sqlite3.connect(database.database_path) as connection:
        connection.row_factory = sqlite3.Row
        test = connection.execute(
            "SELECT nodeid, file_path, last_seen_run_uid, last_duration_ms FROM tests WHERE nodeid = ?",
            ("tests/test_sample.py::test_one",),
        ).fetchone()
        results = connection.execute(
            "SELECT nodeid, outcome, duration_ms FROM test_results WHERE run_uid = ?",
            ("run-tests",),
        ).fetchall()

    assert test["nodeid"] == "tests/test_sample.py::test_one"
    assert test["file_path"] == "tests/test_sample.py"
    assert test["last_seen_run_uid"] == "run-tests"
    assert test["last_duration_ms"] == 250
    results_by_nodeid = {result["nodeid"]: result for result in results}
    assert results_by_nodeid["tests/test_sample.py::test_one"]["outcome"] == "passed"
    assert results_by_nodeid["tests/test_sample.py::test_one"]["duration_ms"] == 250
    assert results_by_nodeid["tests/test_sample.py::test_two"]["outcome"] == "failed"
    assert results_by_nodeid["tests/test_sample.py::test_two"]["duration_ms"] == 125
