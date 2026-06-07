import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path

from pytest_alchemist.database.facade import DATABASE_FILE_NAME, DatabaseFacade
from pytest_alchemist.test_runner.runner import ARTIFACTS_DIR_NAME
from pytest_alchemist.coverage_analysis.models import (
    CoverageArcFact,
    CoverageArtifactMetadata,
    CoverageEntity,
    CoverageLineFact,
)


def _git(project_path: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=project_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _write_test_report(
    project_path: Path,
    *,
    uid: str = "run-1",
    coverage: dict | None = None,
    runned_tests: dict | None = None,
    selected_tests: list[str] | None = None,
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
            "selected_tests": selected_tests
            if selected_tests is not None
            else ["tests/test_sample.py::test_one"],
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
        "coverage_artifacts",
        "coverage_entities",
        "coverage_line_facts",
        "coverage_arc_facts",
    }.issubset(table_names)
    assert "test_results" not in table_names

    with sqlite3.connect(database.database_path) as connection:
        connection.row_factory = sqlite3.Row
        columns_by_table = {
            table_name: {
                row["name"]
                for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
            }
            for table_name in (
                "test_runs",
                "tests",
                "coverage_artifacts",
                "coverage_entities",
                "coverage_line_facts",
                "coverage_arc_facts",
            )
        }

    assert {
        "git_branch",
        "git_commit",
        "git_is_dirty",
    }.issubset(columns_by_table["test_runs"])
    assert {
        "normalized_hash",
        "current_revision",
        "last_outcome",
        "last_error_message",
    }.issubset(columns_by_table["tests"])
    assert "run_uid" in columns_by_table["coverage_artifacts"]
    assert "run_uid" not in columns_by_table["coverage_entities"]
    assert "run_uid" not in columns_by_table["coverage_line_facts"]
    assert "run_uid" not in columns_by_table["coverage_arc_facts"]
    assert "current_revision" in columns_by_table["coverage_entities"]
    assert {
        "observed_entity_revision",
        "observed_test_revision",
        "last_confirmed_run_uid",
        "last_confirmed_at",
    }.issubset(columns_by_table["coverage_line_facts"])
    assert {
        "observed_entity_revision",
        "observed_test_revision",
        "last_confirmed_run_uid",
        "last_confirmed_at",
    }.issubset(columns_by_table["coverage_arc_facts"])


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
    assert run["git_branch"] is None
    assert run["git_commit"] is None
    assert run["git_is_dirty"] is None


def test_save_test_run_persists_git_metadata(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "tests@example.com")
    _git(tmp_path, "config", "user.name", "Tests")
    (tmp_path / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "baseline")
    (tmp_path / "module.py").write_text("VALUE = 2\n", encoding="utf-8")

    database = DatabaseFacade(project_path=tmp_path)
    report_path = _write_test_report(tmp_path, uid="run-git")

    database.save_test_run(report_path)

    with sqlite3.connect(database.database_path) as connection:
        connection.row_factory = sqlite3.Row
        run = connection.execute(
            """
            SELECT git_branch, git_commit, git_is_dirty
            FROM test_runs
            WHERE uid = ?
            """,
            ("run-git",),
        ).fetchone()

    assert run["git_branch"] in {"master", "main"}
    assert run["git_commit"] == _git(tmp_path, "rev-parse", "HEAD")
    assert run["git_is_dirty"] == 1


def test_git_stdout_preserves_utf8_output(monkeypatch, tmp_path: Path) -> None:
    from pytest_alchemist.database import facade as facade_module

    calls = []

    def fake_run_captured_text(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(
            args,
            0,
            stdout="branch-😇\n",
            stderr="",
        )

    monkeypatch.setattr(
        facade_module,
        "run_captured_text",
        fake_run_captured_text,
    )

    assert facade_module._git_stdout(tmp_path, ["rev-parse", "--abbrev-ref", "HEAD"]) == (
        "branch-😇"
    )
    assert calls == [
        (
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            {"cwd": tmp_path, "check": True},
        )
    ]


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


def test_save_test_run_persists_sqlite_coverage_artifact(tmp_path: Path) -> None:
    database = DatabaseFacade(project_path=tmp_path)
    run_dir = tmp_path / ARTIFACTS_DIR_NAME / "test-runs" / "run-sqlite"
    run_dir.mkdir(parents=True)
    coverage_sqlite_path = run_dir / ".coverage"
    coverage_sqlite_path.write_bytes(b"sqlite coverage")
    report_path = _write_test_report(
        tmp_path,
        uid="run-sqlite",
        coverage={
            "format": "sqlite",
            "coverage_json_path": None,
            "coverage_xml_path": None,
            "coverage_sqlite_path": str(coverage_sqlite_path),
        },
    )

    database.save_test_run(report_path)

    with sqlite3.connect(database.database_path) as connection:
        connection.row_factory = sqlite3.Row
        artifact = connection.execute(
            "SELECT run_uid, format, path, sha256 FROM coverage_artifacts"
        ).fetchone()

    assert artifact["run_uid"] == "run-sqlite"
    assert artifact["format"] == "sqlite"
    assert artifact["path"] == str(coverage_sqlite_path)
    assert artifact["sha256"] == hashlib.sha256(coverage_sqlite_path.read_bytes()).hexdigest()


def test_database_persists_normalized_coverage_facts_idempotently(
    tmp_path: Path,
) -> None:
    database = DatabaseFacade(project_path=tmp_path)
    report_path = _write_test_report(tmp_path, uid="run-facts")
    database.save_test_run(report_path)
    metadata = CoverageArtifactMetadata(
        run_uid="run-facts",
        path=str(report_path.parent / ".coverage"),
        sha256="abc",
        coverage_py_version="7.13.5",
        has_contexts=True,
        has_arcs=True,
        quality="complete",
    )
    entities = [
        CoverageEntity(
            id=1,
            file_path="calc.py",
            module_name="calc",
            qualified_name="calc",
            kind="module",
            start_line=1,
            end_line=5,
            normalized_hash="module-hash",
            current_revision=1,
            parent_id=None,
        ),
        CoverageEntity(
            id=2,
            file_path="calc.py",
            module_name="calc",
            qualified_name="calc.add",
            kind="function",
            start_line=1,
            end_line=2,
            normalized_hash="function-hash",
            current_revision=1,
            parent_id=1,
        ),
    ]
    line_facts = [
        CoverageLineFact(
            nodeid="tests/test_calc.py::test_add",
            phase="run",
            entity_id=2,
            raw_line=2,
            entity_line_offset=1,
        )
    ]
    arc_facts = [
        CoverageArcFact(
            nodeid="tests/test_calc.py::test_add",
            phase="run",
            entity_id=2,
            from_line=1,
            to_line=2,
            from_offset=0,
            to_offset=1,
            arc_hash="arc-hash",
        )
    ]

    database.save_coverage_artifact_metadata(metadata)
    database.replace_coverage_facts("run-facts", entities, line_facts, arc_facts)
    database.replace_coverage_facts("run-facts", entities, line_facts, arc_facts)

    tests = database.list_coverage_tests()
    covered_entities = database.list_entities_covered_by_test(
        "tests/test_calc.py::test_add",
    )
    arcs = database.list_arcs_covered_by_test(
        "tests/test_calc.py::test_add",
    )

    assert tests == ["tests/test_calc.py::test_add"]
    assert [entity.qualified_name for entity in covered_entities] == ["calc.add"]
    assert len(arcs) == 1
    assert arcs[0].arc_hash == "arc-hash"

    with sqlite3.connect(database.database_path) as connection:
        connection.row_factory = sqlite3.Row
        artifact = connection.execute(
            "SELECT quality, has_contexts, has_arcs FROM coverage_artifacts"
        ).fetchone()
        entity_count = connection.execute(
            "SELECT COUNT(*) FROM coverage_entities"
        ).fetchone()[0]
        line_fact = connection.execute(
            """
            SELECT
              observed_entity_revision,
              observed_test_revision,
              last_confirmed_run_uid,
              last_confirmed_at
            FROM coverage_line_facts
            """
        ).fetchone()
        line_count = connection.execute("SELECT COUNT(*) FROM coverage_line_facts").fetchone()[0]

    assert artifact["quality"] == "complete"
    assert artifact["has_contexts"] == 1
    assert artifact["has_arcs"] == 1
    assert entity_count == 2
    assert line_count == 1
    assert line_fact["observed_entity_revision"] == 1
    assert line_fact["observed_test_revision"] == 1
    assert line_fact["last_confirmed_run_uid"] == "run-facts"
    assert line_fact["last_confirmed_at"]


def test_database_projects_current_coverage_records_and_line_matches(
    tmp_path: Path,
) -> None:
    database = DatabaseFacade(project_path=tmp_path)
    report_path = _write_test_report(
        tmp_path,
        uid="run-current",
        runned_tests={
            "tests/test_calc.py::test_add": {
                "nodeid": "tests/test_calc.py::test_add",
                "outcome": "passed",
                "duration_ms": 10,
            },
            "tests/test_calc.py::test_subtract": {
                "nodeid": "tests/test_calc.py::test_subtract",
                "outcome": "passed",
                "duration_ms": 12,
            },
        },
    )
    database.save_test_run(report_path)
    metadata = CoverageArtifactMetadata(
        run_uid="run-current",
        path=str(report_path.parent / ".coverage"),
        sha256="abc",
        coverage_py_version="7.13.5",
        has_contexts=True,
        has_arcs=True,
        quality="complete",
    )
    database.save_coverage_artifact_metadata(metadata)
    database.replace_coverage_facts(
        "run-current",
        [
            CoverageEntity(
                id=1,
                file_path="calc.py",
                module_name="calc",
                qualified_name="calc",
                kind="module",
                start_line=1,
                end_line=5,
                normalized_hash="module-hash",
                current_revision=1,
                parent_id=None,
            )
        ],
        [
            CoverageLineFact(
                nodeid="tests/test_calc.py::test_add",
                phase="run",
                entity_id=1,
                raw_line=2,
                entity_line_offset=1,
            ),
            CoverageLineFact(
                nodeid="tests/test_calc.py::test_subtract",
                phase="run",
                entity_id=1,
                raw_line=2,
                entity_line_offset=1,
            ),
            CoverageLineFact(
                nodeid="tests/test_calc.py::test_subtract",
                phase="run",
                entity_id=1,
                raw_line=4,
                entity_line_offset=3,
            ),
        ],
        [],
    )

    records = database.list_coverage_records()
    matches = database.list_tests_covering_lines("calc.py", [2, 4, 99])

    assert [(record.test_nodeid, record.file_path, record.lines) for record in records] == [
        ("tests/test_calc.py::test_add", "calc.py", [2]),
        ("tests/test_calc.py::test_subtract", "calc.py", [2, 4]),
    ]
    assert matches == {
        2: [
            "tests/test_calc.py::test_add",
            "tests/test_calc.py::test_subtract",
        ],
        4: ["tests/test_calc.py::test_subtract"],
    }
    assert database.get_latest_coverage_quality() == "complete"


def test_save_test_run_upserts_latest_test_state(tmp_path: Path) -> None:
    tests_path = tmp_path / "tests"
    tests_path.mkdir()
    (tests_path / "test_sample.py").write_text(
        "\n".join(
            [
                "def test_one():",
                "    assert True",
                "",
                "def test_two():",
                "    assert False",
                "",
            ]
        ),
        encoding="utf-8",
    )
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
            """
            SELECT
              nodeid,
              file_path,
              normalized_hash,
              current_revision,
              last_seen_run_uid,
              last_duration_ms,
              last_outcome,
              last_error_message
            FROM tests
            WHERE nodeid = ?
            """,
            ("tests/test_sample.py::test_one",),
        ).fetchone()
        tests = connection.execute(
            """
            SELECT nodeid, last_outcome, last_duration_ms, last_error_message
            FROM tests
            ORDER BY nodeid
            """
        ).fetchall()

    assert test["nodeid"] == "tests/test_sample.py::test_one"
    assert test["file_path"] == "tests/test_sample.py"
    assert test["normalized_hash"]
    assert test["current_revision"] == 1
    assert test["last_seen_run_uid"] == "run-tests"
    assert test["last_duration_ms"] == 250
    assert test["last_outcome"] == "passed"
    assert test["last_error_message"] is None
    tests_by_nodeid = {test_row["nodeid"]: test_row for test_row in tests}
    assert tests_by_nodeid["tests/test_sample.py::test_one"]["last_outcome"] == "passed"
    assert tests_by_nodeid["tests/test_sample.py::test_one"]["last_duration_ms"] == 250
    assert tests_by_nodeid["tests/test_sample.py::test_one"]["last_error_message"] is None
    assert tests_by_nodeid["tests/test_sample.py::test_two"]["last_outcome"] == "failed"
    assert tests_by_nodeid["tests/test_sample.py::test_two"]["last_duration_ms"] == 125
    assert tests_by_nodeid["tests/test_sample.py::test_two"]["last_error_message"] is None


def test_save_test_run_keeps_latest_known_state_for_tests_not_in_partial_run(
    tmp_path: Path,
) -> None:
    database = DatabaseFacade(project_path=tmp_path)
    full_run_path = _write_test_report(
        tmp_path,
        uid="run-full",
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
        selected_tests=[],
    )
    partial_run_path = _write_test_report(
        tmp_path,
        uid="run-partial",
        runned_tests={
            "tests/test_sample.py::test_one": {
                "nodeid": "tests/test_sample.py::test_one",
                "outcome": "failed",
                "duration_ms": 275,
            },
        },
        selected_tests=["tests/test_sample.py::test_one"],
    )

    database.save_test_run(full_run_path)
    database.save_test_run(partial_run_path)

    with sqlite3.connect(database.database_path) as connection:
        connection.row_factory = sqlite3.Row
        tests = connection.execute(
            """
            SELECT nodeid, last_seen_run_uid, last_outcome, last_duration_ms
            FROM tests
            ORDER BY nodeid
            """
        ).fetchall()

    tests_by_nodeid = {test["nodeid"]: test for test in tests}
    assert tests_by_nodeid["tests/test_sample.py::test_one"]["last_seen_run_uid"] == (
        "run-partial"
    )
    assert tests_by_nodeid["tests/test_sample.py::test_one"]["last_outcome"] == "failed"
    assert tests_by_nodeid["tests/test_sample.py::test_one"]["last_duration_ms"] == 275
    assert tests_by_nodeid["tests/test_sample.py::test_two"]["last_seen_run_uid"] == (
        "run-full"
    )
    assert tests_by_nodeid["tests/test_sample.py::test_two"]["last_outcome"] == "failed"
    assert tests_by_nodeid["tests/test_sample.py::test_two"]["last_duration_ms"] == 125
