"""SQLite-backed database facade."""

from __future__ import annotations

import hashlib
import json
import ast
import sqlite3
import subprocess
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

    def list_tests(self) -> list[TestCase]:
        """Return tests currently known from SQLite."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT nodeid, file_path, last_duration_ms
                FROM tests
                ORDER BY nodeid
                """
            ).fetchall()

        return [
            TestCase(
                nodeid=row["nodeid"],
                file_path=row["file_path"],
                estimated_duration=(row["last_duration_ms"] or 0) / 1000,
            )
            for row in rows
        ]

    def list_coverage_records(self) -> list[CoverageRecord]:
        """Return current line coverage grouped by test and file."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                  lf.nodeid,
                  e.file_path,
                  lf.raw_line
                FROM coverage_line_facts lf
                JOIN coverage_entities e ON e.id = lf.entity_id
                ORDER BY lf.nodeid, e.file_path, lf.raw_line
                """
            ).fetchall()

        lines_by_record: dict[tuple[str, str], list[int]] = {}
        for row in rows:
            lines_by_record.setdefault(
                (row["nodeid"], row["file_path"]),
                [],
            ).append(row["raw_line"])

        return [
            CoverageRecord(
                test_nodeid=nodeid,
                file_path=file_path,
                lines=sorted(set(lines)),
            )
            for (nodeid, file_path), lines in sorted(lines_by_record.items())
        ]

    def list_tests_covering_lines(
        self,
        file_path: str,
        lines: list[int],
    ) -> dict[int, list[str]]:
        """Return current tests that covered each requested raw line."""

        if not lines:
            return {}

        placeholders = ", ".join("?" for _ in lines)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT DISTINCT
                  lf.raw_line,
                  lf.nodeid
                FROM coverage_line_facts lf
                JOIN coverage_entities e ON e.id = lf.entity_id
                WHERE e.file_path = ?
                  AND lf.raw_line IN ({placeholders})
                ORDER BY lf.raw_line, lf.nodeid
                """,
                (file_path, *lines),
            ).fetchall()

        tests_by_line: dict[int, list[str]] = {}
        for row in rows:
            tests_by_line.setdefault(row["raw_line"], []).append(row["nodeid"])
        return tests_by_line

    def get_latest_coverage_quality(self) -> str | None:
        """Return quality of the latest normalized native coverage artifact."""

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT quality
                FROM coverage_artifacts
                WHERE format = 'sqlite'
                  AND quality IS NOT NULL
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
        return str(row["quality"]) if row else None

    def get_latest_coverage_status(self) -> dict[str, Any] | None:
        """Return dashboard metadata for the latest normalized coverage artifact."""

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                  ca.run_uid,
                  ca.created_at,
                  ca.quality,
                  tr.git_branch,
                  tr.git_commit,
                  tr.git_is_dirty
                FROM coverage_artifacts ca
                LEFT JOIN test_runs tr ON tr.uid = ca.run_uid
                WHERE ca.format = 'sqlite'
                  AND ca.quality IS NOT NULL
                ORDER BY ca.created_at DESC, ca.id DESC
                LIMIT 1
                """
            ).fetchone()
        return dict(row) if row else None

    def get_latest_test_run_status(self) -> dict[str, Any] | None:
        """Return dashboard metadata for the latest persisted test run."""

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                  uid,
                  finished_at,
                  status,
                  git_branch,
                  git_commit,
                  git_is_dirty
                FROM test_runs
                ORDER BY created_at DESC, uid DESC
                LIMIT 1
                """
            ).fetchone()
        return dict(row) if row else None

    def get_dashboard_counts(self) -> dict[str, int]:
        """Return project-local counts needed by the interactive dashboard."""

        with self._connect() as connection:
            return {
                "coverage_entity_count": _count_table(connection, "coverage_entities"),
                "coverage_line_fact_count": _count_table(connection, "coverage_line_facts"),
                "coverage_arc_fact_count": _count_table(connection, "coverage_arc_facts"),
                "known_test_count": _count_table(connection, "tests"),
            }

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
        """Replace the project's current normalized coverage snapshot."""

        with self._connect() as connection:
            connection.execute("DELETE FROM coverage_arc_facts")
            connection.execute("DELETE FROM coverage_line_facts")
            connection.execute("DELETE FROM coverage_entities")

            entity_id_map: dict[int, int] = {}
            entity_revision_map: dict[int, int] = {}
            for entity in entities:
                parent_id = (
                    entity_id_map[entity.parent_id]
                    if entity.parent_id is not None
                    else None
                )
                cursor = connection.execute(
                    """
                    INSERT INTO coverage_entities (
                      file_path,
                      module_name,
                      qualified_name,
                      kind,
                      start_line,
                      end_line,
                      normalized_hash,
                      current_revision,
                      parent_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entity.file_path,
                        entity.module_name,
                        entity.qualified_name,
                        entity.kind,
                        entity.start_line,
                        entity.end_line,
                        entity.normalized_hash,
                        entity.current_revision,
                        parent_id,
                    ),
                )
                if entity.id is not None:
                    entity_id_map[entity.id] = int(cursor.lastrowid)
                    entity_revision_map[entity.id] = entity.current_revision

            now = _timestamp()
            for fact in line_facts:
                observed_test_revision = self._current_test_revision(
                    connection,
                    fact.nodeid,
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO coverage_line_facts (
                      nodeid,
                      phase,
                      entity_id,
                      raw_line,
                      entity_line_offset,
                      observed_entity_revision,
                      observed_test_revision,
                      last_confirmed_run_uid,
                      last_confirmed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fact.nodeid,
                        fact.phase,
                        entity_id_map[fact.entity_id],
                        fact.raw_line,
                        fact.entity_line_offset,
                        entity_revision_map[fact.entity_id],
                        observed_test_revision,
                        run_uid,
                        now,
                    ),
                )

            for fact in arc_facts:
                observed_test_revision = self._current_test_revision(
                    connection,
                    fact.nodeid,
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO coverage_arc_facts (
                      nodeid,
                      phase,
                      entity_id,
                      from_line,
                      to_line,
                      from_offset,
                      to_offset,
                      arc_hash,
                      observed_entity_revision,
                      observed_test_revision,
                      last_confirmed_run_uid,
                      last_confirmed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fact.nodeid,
                        fact.phase,
                        entity_id_map[fact.entity_id],
                        fact.from_line,
                        fact.to_line,
                        fact.from_offset,
                        fact.to_offset,
                        fact.arc_hash,
                        entity_revision_map[fact.entity_id],
                        observed_test_revision,
                        run_uid,
                        now,
                    ),
                )

    def list_coverage_tests(self) -> list[str]:
        """Return test node ids observed in current normalized coverage facts."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT nodeid FROM coverage_line_facts
                UNION
                SELECT nodeid FROM coverage_arc_facts
                ORDER BY nodeid
                """,
            ).fetchall()
        return [row["nodeid"] for row in rows]

    def list_entities_covered_by_test(
        self,
        nodeid: str,
    ) -> list[CoverageEntity]:
        """Return current entities covered by a test."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT e.*
                FROM coverage_entities e
                WHERE e.id IN (
                  SELECT entity_id
                  FROM coverage_line_facts
                  WHERE nodeid = ?
                  UNION
                  SELECT entity_id
                  FROM coverage_arc_facts
                  WHERE nodeid = ?
                )
                ORDER BY e.file_path, e.start_line, e.qualified_name
                """,
                (nodeid, nodeid),
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
        nodeid: str,
    ) -> list[CoverageArcFact]:
        """Return current branch arcs covered by a test."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM coverage_arc_facts
                WHERE nodeid = ?
                ORDER BY entity_id, from_line, to_line
                """,
                (nodeid,),
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
        project_root = Path(report["project_root"])
        now = _timestamp()
        selected_nodeids = report["selection"]["selected_tests"]
        coverage_enabled = int(coverage is not None)
        duration_ms = int(round(float(report["duration_seconds"]) * 1000))
        git_branch, git_commit, git_is_dirty = _read_git_snapshot(project_root)

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
                  git_branch,
                  git_commit,
                  git_is_dirty,
                  created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    git_branch,
                    git_commit,
                    None if git_is_dirty is None else int(git_is_dirty),
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
                    project_root,
                    test_duration_ms,
                    test_result["outcome"],
                    None,
                    now,
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
                  git_branch TEXT,
                  git_commit TEXT,
                  git_is_dirty INTEGER,
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tests (
                  nodeid TEXT PRIMARY KEY,
                  file_path TEXT NOT NULL,
                  normalized_hash TEXT,
                  current_revision INTEGER NOT NULL DEFAULT 1,
                  last_seen_run_uid TEXT,
                  last_duration_ms INTEGER,
                  last_outcome TEXT,
                  last_error_message TEXT,
                  first_seen_at TEXT NOT NULL,
                  last_seen_at TEXT NOT NULL,
                  FOREIGN KEY (last_seen_run_uid) REFERENCES test_runs(uid)
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
                  file_path TEXT NOT NULL,
                  module_name TEXT,
                  qualified_name TEXT,
                  kind TEXT NOT NULL,
                  start_line INTEGER,
                  end_line INTEGER,
                  normalized_hash TEXT,
                  current_revision INTEGER NOT NULL DEFAULT 1,
                  parent_id INTEGER,
                  FOREIGN KEY (parent_id) REFERENCES coverage_entities(id)
                );

                CREATE TABLE IF NOT EXISTS coverage_line_facts (
                  nodeid TEXT NOT NULL,
                  phase TEXT NOT NULL,
                  entity_id INTEGER NOT NULL,
                  raw_line INTEGER NOT NULL,
                  entity_line_offset INTEGER,
                  observed_entity_revision INTEGER NOT NULL,
                  observed_test_revision INTEGER NOT NULL,
                  last_confirmed_run_uid TEXT NOT NULL,
                  last_confirmed_at TEXT NOT NULL,
                  PRIMARY KEY (nodeid, phase, entity_id, raw_line),
                  FOREIGN KEY (last_confirmed_run_uid) REFERENCES test_runs(uid),
                  FOREIGN KEY (entity_id) REFERENCES coverage_entities(id)
                );

                CREATE TABLE IF NOT EXISTS coverage_arc_facts (
                  nodeid TEXT NOT NULL,
                  phase TEXT NOT NULL,
                  entity_id INTEGER NOT NULL,
                  from_line INTEGER NOT NULL,
                  to_line INTEGER NOT NULL,
                  from_offset INTEGER,
                  to_offset INTEGER,
                  arc_hash TEXT NOT NULL,
                  observed_entity_revision INTEGER NOT NULL,
                  observed_test_revision INTEGER NOT NULL,
                  last_confirmed_run_uid TEXT NOT NULL,
                  last_confirmed_at TEXT NOT NULL,
                  PRIMARY KEY (
                    nodeid,
                    phase,
                    entity_id,
                    from_line,
                    to_line
                  ),
                  FOREIGN KEY (last_confirmed_run_uid) REFERENCES test_runs(uid),
                  FOREIGN KEY (entity_id) REFERENCES coverage_entities(id)
                );
                """
            )
            for column_name, column_type in (
                ("git_branch", "TEXT"),
                ("git_commit", "TEXT"),
                ("git_is_dirty", "INTEGER"),
            ):
                _ensure_column(connection, "test_runs", column_name, column_type)
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
        project_root: Path,
        duration_ms: int,
        outcome: str,
        error_message: str | None,
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
              normalized_hash,
              current_revision,
              last_seen_run_uid,
              last_duration_ms,
              last_outcome,
              last_error_message,
              first_seen_at,
              last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                nodeid,
                file_path,
                _normalized_test_hash(project_root, nodeid),
                1,
                run_uid,
                duration_ms,
                outcome,
                error_message,
                first_seen_at,
                now,
            ),
        )

    def _current_test_revision(
        self,
        connection: sqlite3.Connection,
        nodeid: str,
    ) -> int:
        row = connection.execute(
            "SELECT current_revision FROM tests WHERE nodeid = ?",
            (nodeid,),
        ).fetchone()
        return int(row["current_revision"]) if row else 1


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
        file_path=row["file_path"],
        module_name=row["module_name"],
        qualified_name=row["qualified_name"],
        kind=row["kind"],
        start_line=row["start_line"],
        end_line=row["end_line"],
        normalized_hash=row["normalized_hash"],
        current_revision=row["current_revision"],
        parent_id=row["parent_id"],
    )


def _arc_fact_from_row(row: sqlite3.Row) -> CoverageArcFact:
    return CoverageArcFact(
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


def _count_table(connection: sqlite3.Connection, table_name: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])


def _file_path_from_nodeid(nodeid: str) -> str:
    return nodeid.split("::", maxsplit=1)[0]


def _normalized_test_hash(project_root: Path, nodeid: str) -> str | None:
    relative_path, *symbol_parts = nodeid.split("::")
    source_path = project_root / relative_path
    if not source_path.exists():
        return None

    try:
        source = source_path.read_text(encoding="utf-8")
        module = ast.parse(source)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None

    target: ast.AST = module
    for symbol_part in symbol_parts:
        symbol_name = symbol_part.split("[", maxsplit=1)[0]
        body = getattr(target, "body", [])
        match = next(
            (
                node
                for node in body
                if isinstance(
                    node,
                    (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                )
                and node.name == symbol_name
            ),
            None,
        )
        if match is None:
            return None
        target = match

    return hashlib.sha256(
        ast.dump(target, annotate_fields=True, include_attributes=False).encode("utf-8")
    ).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_git_snapshot(project_path: Path) -> tuple[str | None, str | None, bool | None]:
    branch = _git_stdout(project_path, ["rev-parse", "--abbrev-ref", "HEAD"])
    commit = _git_stdout(project_path, ["rev-parse", "HEAD"])
    if branch is None or commit is None:
        return None, None, None

    status = _git_stdout(project_path, ["status", "--porcelain"])
    return branch, commit, None if status is None else bool(status)


def _git_stdout(project_path: Path, args: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=project_path,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip()


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
