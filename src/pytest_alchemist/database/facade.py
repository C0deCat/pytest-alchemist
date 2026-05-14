"""SQLite-backed database facade with temporary mock history fallbacks."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pytest_alchemist.coverage_analysis.models import CoverageRecord
from pytest_alchemist.diff_picker.models import ChangedCode
from pytest_alchemist.test_runner.models import TestCase

ARTIFACTS_DIR_NAME = ".pytest-alchemist-artifacts"
DATABASE_FILE_NAME = "pytest-alchemist.sqlite"


class DatabaseFacade:
    """Persistence facade for project-local pytest-alchemist data."""

    def __init__(self, project_path: str | Path | None = None) -> None:
        self.project_path = Path(project_path or Path.cwd()).resolve()
        self.artifacts_path = self.project_path / ARTIFACTS_DIR_NAME
        self.database_path = self.artifacts_path / DATABASE_FILE_NAME
        self.artifacts_path.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()
        self._tests = _build_mock_tests()
        self._coverage_records = _build_mock_coverage_records()
        self._coverage_collection_runs: list[list[CoverageRecord]] = []

    def list_tests(self) -> list[TestCase]:
        """Return tests known from SQLite plus temporary mock history."""

        tests_by_nodeid = {test.nodeid: test for test in self._tests}
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT nodeid, file_path, last_duration_ms
                FROM tests
                ORDER BY nodeid
                """
            ).fetchall()

        for row in rows:
            tests_by_nodeid[row["nodeid"]] = TestCase(
                nodeid=row["nodeid"],
                file_path=row["file_path"],
                estimated_duration=(row["last_duration_ms"] or 0) / 1000,
            )

        return list(tests_by_nodeid.values())

    def list_coverage_records(self) -> list[CoverageRecord]:
        """Return temporary mock coverage records until coverage persistence exists."""

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
        """Store collected coverage in memory until coverage persistence exists."""

        self._coverage_collection_runs.append(list(records))

    def save_test_run(self, test_report_path: str | Path) -> None:
        """Persist a test run from its JSON report."""

        report = json.loads(Path(test_report_path).read_text(encoding="utf-8"))
        summary = report["summary"]
        pytest_data = report["pytest"]
        coverage = report.get("coverage")
        runned_tests = report.get("runned_tests", {})
        run_uid = report["uid"]
        now = _timestamp()
        selected_nodeids = report["selection"]["selected_tests"]
        coverage_enabled = int(coverage is not None)
        duration_ms = int(round(float(report["duration_seconds"]) * 1000))

        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO test_runs (
                  uid,
                  started_at,
                  finished_at,
                  status,
                  exit_code,
                  duration_ms,
                  passed_count,
                  failed_count,
                  coverage_enabled,
                  selected_nodeids_json,
                  stdout_path,
                  stderr_path,
                  project_root,
                  pytest_args_json,
                  created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_uid,
                    report["started_at"],
                    report["finished_at"],
                    report["status"],
                    report["exit_code"],
                    duration_ms,
                    summary["passed"],
                    summary["failed"],
                    coverage_enabled,
                    json.dumps(selected_nodeids),
                    pytest_data["stdout_path"],
                    pytest_data["stderr_path"],
                    report["project_root"],
                    json.dumps(pytest_data["args"]),
                    now,
                ),
            )

            for test_result in runned_tests.values():
                nodeid = test_result["nodeid"]
                test_duration_ms = int(test_result.get("duration_ms") or 0)
                self._upsert_test(
                    connection,
                    nodeid,
                    run_uid,
                    test_duration_ms,
                    now,
                )
                connection.execute(
                    """
                    INSERT OR REPLACE INTO test_results (
                      run_uid,
                      nodeid,
                      outcome,
                      duration_ms,
                      error_message
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        run_uid,
                        nodeid,
                        test_result["outcome"],
                        test_duration_ms,
                        None,
                    ),
                )

            for artifact_format, artifact_path in _coverage_paths(report):
                path = Path(artifact_path)
                if not path.exists():
                    continue
                connection.execute(
                    """
                    INSERT INTO coverage_artifacts (
                      run_uid,
                      format,
                      path,
                      sha256,
                      created_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        run_uid,
                        artifact_format,
                        artifact_path,
                        _sha256(path),
                        now,
                    ),
                )

    def _initialize_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS test_runs (
                  uid TEXT PRIMARY KEY,
                  started_at TEXT NOT NULL,
                  finished_at TEXT,
                  status TEXT NOT NULL,
                  exit_code INTEGER,
                  duration_ms INTEGER,
                  passed_count INTEGER,
                  failed_count INTEGER,
                  coverage_enabled INTEGER NOT NULL,
                  selected_nodeids_json TEXT NOT NULL DEFAULT '[]',
                  stdout_path TEXT,
                  stderr_path TEXT,
                  project_root TEXT NOT NULL,
                  pytest_args_json TEXT NOT NULL DEFAULT '[]',
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tests (
                  nodeid TEXT PRIMARY KEY,
                  file_path TEXT NOT NULL,
                  last_seen_run_uid TEXT,
                  last_duration_ms INTEGER,
                  first_seen_at TEXT NOT NULL,
                  last_seen_at TEXT NOT NULL,
                  FOREIGN KEY (last_seen_run_uid) REFERENCES test_runs(uid)
                );

                CREATE TABLE IF NOT EXISTS test_results (
                  run_uid TEXT NOT NULL,
                  nodeid TEXT NOT NULL,
                  outcome TEXT NOT NULL,
                  duration_ms INTEGER,
                  error_message TEXT,
                  PRIMARY KEY (run_uid, nodeid),
                  FOREIGN KEY (run_uid) REFERENCES test_runs(uid),
                  FOREIGN KEY (nodeid) REFERENCES tests(nodeid)
                );

                CREATE TABLE IF NOT EXISTS coverage_artifacts (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  run_uid TEXT NOT NULL,
                  format TEXT NOT NULL,
                  path TEXT NOT NULL,
                  sha256 TEXT,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY (run_uid) REFERENCES test_runs(uid)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _upsert_test(
        self,
        connection: sqlite3.Connection,
        nodeid: str,
        run_uid: str,
        duration_ms: int,
        now: str,
    ) -> None:
        file_path = _file_path_from_nodeid(nodeid)
        existing = connection.execute(
            "SELECT first_seen_at FROM tests WHERE nodeid = ?",
            (nodeid,),
        ).fetchone()
        first_seen_at = existing["first_seen_at"] if existing else now
        connection.execute(
            """
            INSERT OR REPLACE INTO tests (
              nodeid,
              file_path,
              last_seen_run_uid,
              last_duration_ms,
              first_seen_at,
              last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (nodeid, file_path, run_uid, duration_ms, first_seen_at, now),
        )


def _build_mock_tests() -> list[TestCase]:
    return [
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


def _build_mock_coverage_records() -> list[CoverageRecord]:
    return [
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


def _coverage_paths(report: dict[str, Any]) -> list[tuple[str, str]]:
    coverage = report.get("coverage")
    if coverage is None:
        return []

    paths: list[tuple[str, str]] = []
    if coverage.get("coverage_json_path"):
        paths.append(("json", coverage["coverage_json_path"]))
    if coverage.get("coverage_xml_path"):
        paths.append(("xml", coverage["coverage_xml_path"]))
    return paths


def _file_path_from_nodeid(nodeid: str) -> str:
    return nodeid.split("::", maxsplit=1)[0]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
