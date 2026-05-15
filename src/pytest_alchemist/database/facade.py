"""SQLite-backed database facade with temporary mock history fallbacks."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pytest_alchemist.coverage_analysis.models import (
    CoverageArcFact,
    CoverageArtifactMetadata,
    CoverageEntity,
    CoverageLineFact,
    CoverageRecord,
)
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

    def save_coverage_artifact_metadata(
        self,
        metadata: CoverageArtifactMetadata,
    ) -> None:
        """Persist metadata for a native Coverage.py artifact."""

        with self._connect() as connection:
            result = connection.execute(
                """
                UPDATE coverage_artifacts
                SET
                  sha256 = ?,
                  coverage_py_version = ?,
                  has_contexts = ?,
                  has_arcs = ?,
                  quality = ?
                WHERE run_uid = ? AND path = ?
                """,
                (
                    metadata.sha256,
                    metadata.coverage_py_version,
                    int(metadata.has_contexts),
                    int(metadata.has_arcs),
                    metadata.quality,
                    metadata.run_uid,
                    metadata.path,
                ),
            )
            if result.rowcount:
                return

            connection.execute(
                """
                INSERT INTO coverage_artifacts (
                  run_uid,
                  format,
                  path,
                  sha256,
                  coverage_py_version,
                  has_contexts,
                  has_arcs,
                  quality,
                  created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    metadata.run_uid,
                    "sqlite",
                    metadata.path,
                    metadata.sha256,
                    metadata.coverage_py_version,
                    int(metadata.has_contexts),
                    int(metadata.has_arcs),
                    metadata.quality,
                    _timestamp(),
                ),
            )

    def replace_coverage_facts(
        self,
        run_uid: str,
        entities: list[CoverageEntity],
        line_facts: list[CoverageLineFact],
        arc_facts: list[CoverageArcFact],
    ) -> None:
        """Replace normalized coverage facts for one run."""

        with self._connect() as connection:
            connection.execute(
                "DELETE FROM coverage_arc_facts WHERE run_uid = ?",
                (run_uid,),
            )
            connection.execute(
                "DELETE FROM coverage_line_facts WHERE run_uid = ?",
                (run_uid,),
            )
            connection.execute(
                "DELETE FROM coverage_entities WHERE run_uid = ?",
                (run_uid,),
            )

            entity_id_map: dict[int, int] = {}
            for entity in entities:
                parent_id = (
                    entity_id_map[entity.parent_id]
                    if entity.parent_id is not None
                    else None
                )
                cursor = connection.execute(
                    """
                    INSERT INTO coverage_entities (
                      run_uid,
                      file_path,
                      module_name,
                      qualified_name,
                      kind,
                      start_line,
                      end_line,
                      normalized_hash,
                      parent_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entity.run_uid,
                        entity.file_path,
                        entity.module_name,
                        entity.qualified_name,
                        entity.kind,
                        entity.start_line,
                        entity.end_line,
                        entity.normalized_hash,
                        parent_id,
                    ),
                )
                if entity.id is not None:
                    entity_id_map[entity.id] = int(cursor.lastrowid)

            for fact in line_facts:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO coverage_line_facts (
                      run_uid,
                      nodeid,
                      phase,
                      entity_id,
                      raw_line,
                      entity_line_offset
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fact.run_uid,
                        fact.nodeid,
                        fact.phase,
                        entity_id_map[fact.entity_id],
                        fact.raw_line,
                        fact.entity_line_offset,
                    ),
                )

            for fact in arc_facts:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO coverage_arc_facts (
                      run_uid,
                      nodeid,
                      phase,
                      entity_id,
                      from_line,
                      to_line,
                      from_offset,
                      to_offset,
                      arc_hash
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fact.run_uid,
                        fact.nodeid,
                        fact.phase,
                        entity_id_map[fact.entity_id],
                        fact.from_line,
                        fact.to_line,
                        fact.from_offset,
                        fact.to_offset,
                        fact.arc_hash,
                    ),
                )

    def list_coverage_tests(self, run_uid: str) -> list[str]:
        """Return test node ids observed in normalized coverage facts."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT nodeid FROM coverage_line_facts WHERE run_uid = ?
                UNION
                SELECT nodeid FROM coverage_arc_facts WHERE run_uid = ?
                ORDER BY nodeid
                """,
                (run_uid, run_uid),
            ).fetchall()
        return [row["nodeid"] for row in rows]

    def list_entities_covered_by_test(
        self,
        run_uid: str,
        nodeid: str,
    ) -> list[CoverageEntity]:
        """Return entities covered by a test in one run."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT e.*
                FROM coverage_entities e
                WHERE e.id IN (
                  SELECT entity_id
                  FROM coverage_line_facts
                  WHERE run_uid = ? AND nodeid = ?
                  UNION
                  SELECT entity_id
                  FROM coverage_arc_facts
                  WHERE run_uid = ? AND nodeid = ?
                )
                ORDER BY e.file_path, e.start_line, e.qualified_name
                """,
                (run_uid, nodeid, run_uid, nodeid),
            ).fetchall()
        return [_entity_from_row(row) for row in rows]

    def list_tests_covering_entity(self, entity_id: int) -> list[str]:
        """Return test node ids that covered a normalized entity."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT nodeid FROM coverage_line_facts WHERE entity_id = ?
                UNION
                SELECT nodeid FROM coverage_arc_facts WHERE entity_id = ?
                ORDER BY nodeid
                """,
                (entity_id, entity_id),
            ).fetchall()
        return [row["nodeid"] for row in rows]

    def list_arcs_covered_by_test(
        self,
        run_uid: str,
        nodeid: str,
    ) -> list[CoverageArcFact]:
        """Return branch arcs covered by a test in one run."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM coverage_arc_facts
                WHERE run_uid = ? AND nodeid = ?
                ORDER BY entity_id, from_line, to_line
                """,
                (run_uid, nodeid),
            ).fetchall()
        return [_arc_fact_from_row(row) for row in rows]

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
                  coverage_py_version TEXT,
                  has_contexts INTEGER,
                  has_arcs INTEGER,
                  quality TEXT,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY (run_uid) REFERENCES test_runs(uid)
                );

                CREATE TABLE IF NOT EXISTS coverage_entities (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  run_uid TEXT NOT NULL,
                  file_path TEXT NOT NULL,
                  module_name TEXT,
                  qualified_name TEXT,
                  kind TEXT NOT NULL,
                  start_line INTEGER,
                  end_line INTEGER,
                  normalized_hash TEXT,
                  parent_id INTEGER,
                  FOREIGN KEY (run_uid) REFERENCES test_runs(uid),
                  FOREIGN KEY (parent_id) REFERENCES coverage_entities(id)
                );

                CREATE TABLE IF NOT EXISTS coverage_line_facts (
                  run_uid TEXT NOT NULL,
                  nodeid TEXT NOT NULL,
                  phase TEXT NOT NULL,
                  entity_id INTEGER NOT NULL,
                  raw_line INTEGER NOT NULL,
                  entity_line_offset INTEGER,
                  PRIMARY KEY (run_uid, nodeid, phase, entity_id, raw_line),
                  FOREIGN KEY (run_uid) REFERENCES test_runs(uid),
                  FOREIGN KEY (entity_id) REFERENCES coverage_entities(id)
                );

                CREATE TABLE IF NOT EXISTS coverage_arc_facts (
                  run_uid TEXT NOT NULL,
                  nodeid TEXT NOT NULL,
                  phase TEXT NOT NULL,
                  entity_id INTEGER NOT NULL,
                  from_line INTEGER NOT NULL,
                  to_line INTEGER NOT NULL,
                  from_offset INTEGER,
                  to_offset INTEGER,
                  arc_hash TEXT NOT NULL,
                  PRIMARY KEY (
                    run_uid,
                    nodeid,
                    phase,
                    entity_id,
                    from_line,
                    to_line
                  ),
                  FOREIGN KEY (run_uid) REFERENCES test_runs(uid),
                  FOREIGN KEY (entity_id) REFERENCES coverage_entities(id)
                );
                """
            )
            for column_name, column_type in (
                ("coverage_py_version", "TEXT"),
                ("has_contexts", "INTEGER"),
                ("has_arcs", "INTEGER"),
                ("quality", "TEXT"),
            ):
                _ensure_column(connection, "coverage_artifacts", column_name, column_type)

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
    if coverage.get("coverage_sqlite_path"):
        paths.append(("sqlite", coverage["coverage_sqlite_path"]))
    return paths


def _entity_from_row(row: sqlite3.Row) -> CoverageEntity:
    return CoverageEntity(
        id=row["id"],
        run_uid=row["run_uid"],
        file_path=row["file_path"],
        module_name=row["module_name"],
        qualified_name=row["qualified_name"],
        kind=row["kind"],
        start_line=row["start_line"],
        end_line=row["end_line"],
        normalized_hash=row["normalized_hash"],
        parent_id=row["parent_id"],
    )


def _arc_fact_from_row(row: sqlite3.Row) -> CoverageArcFact:
    return CoverageArcFact(
        run_uid=row["run_uid"],
        nodeid=row["nodeid"],
        phase=row["phase"],
        entity_id=row["entity_id"],
        from_line=row["from_line"],
        to_line=row["to_line"],
        from_offset=row["from_offset"],
        to_offset=row["to_offset"],
        arc_hash=row["arc_hash"],
    )


def _ensure_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_type: str,
) -> None:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    if column_name in {row["name"] for row in rows}:
        return
    connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


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
