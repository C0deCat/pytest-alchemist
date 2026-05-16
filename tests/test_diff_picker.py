import json
import subprocess
from pathlib import Path

import pytest

from pytest_alchemist.coverage_analysis.models import (
    CoverageArtifactMetadata,
    CoverageEntity,
    CoverageLineFact,
)
from pytest_alchemist.database.facade import DatabaseFacade
from pytest_alchemist.diff_picker.models import ChangedCode
from pytest_alchemist.diff_picker.picker import (
    DiffPicker,
    DiffRangeError,
    _parse_unified_diff,
)
from pytest_alchemist.test_runner.runner import ARTIFACTS_DIR_NAME


def _git(project_path: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=project_path,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(project_path: Path) -> None:
    _git(project_path, "init")
    _git(project_path, "config", "user.email", "tests@example.com")
    _git(project_path, "config", "user.name", "Tests")


def _commit_all(project_path: Path, message: str) -> None:
    _git(project_path, "add", ".")
    _git(project_path, "commit", "-m", message)


def _write_test_report(project_path: Path, uid: str, nodeids: list[str]) -> Path:
    run_dir = project_path / ARTIFACTS_DIR_NAME / "test-runs" / uid
    run_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = run_dir / "stdout.txt"
    stderr_path = run_dir / "stderr.txt"
    coverage_path = run_dir / ".coverage"
    stdout_path.write_text("", encoding="utf-8")
    stderr_path.write_text("", encoding="utf-8")
    coverage_path.write_bytes(b"sqlite coverage")
    report_path = run_dir / "test_report.json"
    report = {
        "schema_version": 1,
        "uid": uid,
        "project_root": str(project_path),
        "started_at": "2026-05-13T01:00:00Z",
        "finished_at": "2026-05-13T01:00:01Z",
        "duration_seconds": 0.1,
        "exit_code": 0,
        "status": "passed",
        "pytest": {
            "args": ["python", "-m", "pytest"],
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        },
        "selection": {"selected_tests": []},
        "summary": {
            "passed": len(nodeids),
            "failed": 0,
            "skipped": 0,
            "total": len(nodeids),
        },
        "runned_tests": {
            nodeid: {
                "nodeid": nodeid,
                "outcome": "passed",
                "duration_ms": 10,
            }
            for nodeid in nodeids
        },
        "coverage": {
            "format": "sqlite",
            "coverage_json_path": None,
            "coverage_xml_path": None,
            "coverage_sqlite_path": str(coverage_path),
        },
        "artifacts": {
            "run_dir": str(run_dir),
            "test_report_path": str(report_path),
        },
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return report_path


def _persist_current_coverage(
    database: DatabaseFacade,
    project_path: Path,
    *,
    quality: str = "complete",
) -> None:
    nodeids = [
        "tests/test_module.py::test_first",
        "tests/test_module.py::test_second",
    ]
    report_path = _write_test_report(project_path, "run-coverage", nodeids)
    database.save_test_run(report_path)
    database.save_coverage_artifact_metadata(
        CoverageArtifactMetadata(
            run_uid="run-coverage",
            path=str(report_path.parent / ".coverage"),
            sha256="abc",
            coverage_py_version="7.13.5",
            has_contexts=quality != "missing_contexts",
            has_arcs=quality != "missing_arcs",
            quality=quality,
        )
    )
    entities = [
        CoverageEntity(
            id=1,
            file_path="src/pkg/module.py",
            module_name="pkg.module",
            qualified_name="pkg.module",
            kind="module",
            start_line=1,
            end_line=10,
            normalized_hash="module-hash",
            current_revision=1,
            parent_id=None,
        )
    ]
    line_facts = [
        CoverageLineFact(
            nodeid="tests/test_module.py::test_first",
            phase="run",
            entity_id=1,
            raw_line=2,
            entity_line_offset=1,
        ),
        CoverageLineFact(
            nodeid="tests/test_module.py::test_second",
            phase="run",
            entity_id=1,
            raw_line=2,
            entity_line_offset=1,
        ),
        CoverageLineFact(
            nodeid="tests/test_module.py::test_second",
            phase="run",
            entity_id=1,
            raw_line=3,
            entity_line_offset=2,
        ),
    ]
    database.replace_coverage_facts("run-coverage", entities, line_facts, [])


def test_parse_unified_diff_separates_added_modified_and_deleted_lines() -> None:
    changes = _parse_unified_diff(
        "\n".join(
            [
                "diff --git a/src/pkg/module.py b/src/pkg/module.py",
                "--- a/src/pkg/module.py",
                "+++ b/src/pkg/module.py",
                "@@ -1,2 +1,3 @@",
                " line one",
                "-old value",
                "+new value",
                "+extra value",
                "@@ -8,1 +9,0 @@",
                "-deleted value",
                "diff --git a/README.md b/README.md",
                "--- a/README.md",
                "+++ b/README.md",
                "@@ -1,0 +1,1 @@",
                "+ignore me",
            ]
        )
    )

    assert changes == [
        ChangedCode(
            file_path="src/pkg/module.py",
            added_lines=[],
            modified_lines=[2, 3],
            deleted_lines=[2, 8],
        )
    ]


def test_parse_unified_diff_acknowledges_deleted_python_files() -> None:
    changes = _parse_unified_diff(
        "\n".join(
            [
                "diff --git a/src/pkg/removed.py b/src/pkg/removed.py",
                "--- a/src/pkg/removed.py",
                "+++ /dev/null",
                "@@ -1,2 +0,0 @@",
                "-VALUE = 1",
                "-VALUE = 2",
            ]
        )
    )

    assert changes == [
        ChangedCode(
            file_path="src/pkg/removed.py",
            added_lines=[],
            modified_lines=[],
            deleted_lines=[1, 2],
        )
    ]


def test_diff_picker_selects_all_tests_covering_changed_current_lines(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    source_path = tmp_path / "src" / "pkg"
    source_path.mkdir(parents=True)
    (source_path / "module.py").write_text(
        "\n".join(["VALUE = 1", "VALUE = 2", "VALUE = 3", ""]),
        encoding="utf-8",
    )
    tests_path = tmp_path / "tests"
    tests_path.mkdir()
    (tests_path / "test_module.py").write_text(
        "\n".join(["def test_first(): pass", "def test_second(): pass", ""]),
        encoding="utf-8",
    )
    _commit_all(tmp_path, "baseline")
    (source_path / "module.py").write_text(
        "\n".join(["VALUE = 1", "VALUE = 20", "VALUE = 30", ""]),
        encoding="utf-8",
    )
    _commit_all(tmp_path, "change current lines")

    database = DatabaseFacade(tmp_path)
    _persist_current_coverage(database, tmp_path)

    selection = DiffPicker(database).pick_candidates(last_commits=1)

    assert [test.nodeid for test in selection.candidates] == [
        "tests/test_module.py::test_first",
        "tests/test_module.py::test_second",
    ]
    assert [change.modified_lines for change in selection.target_changes] == [[2, 3]]
    assert [(item.test_nodeid, item.line) for item in selection.evidence] == [
        ("tests/test_module.py::test_first", 2),
        ("tests/test_module.py::test_second", 2),
        ("tests/test_module.py::test_second", 3),
    ]
    assert selection.diagnostics.codes == [
        "deleted_lines_present_but_unmatched_with_current_coverage"
    ]


def test_diff_picker_reports_deleted_only_changes_without_false_matches(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    source_path = tmp_path / "src" / "pkg"
    source_path.mkdir(parents=True)
    module_path = source_path / "module.py"
    module_path.write_text("VALUE = 1\nREMOVED = 2\n", encoding="utf-8")
    _commit_all(tmp_path, "baseline")
    module_path.write_text("VALUE = 1\n", encoding="utf-8")
    _commit_all(tmp_path, "delete line")

    database = DatabaseFacade(tmp_path)
    _persist_current_coverage(database, tmp_path)

    selection = DiffPicker(database).pick_candidates(last_commits=1)

    assert selection.candidates == []
    assert selection.evidence == []
    assert "deleted_lines_present_but_unmatched_with_current_coverage" in (
        selection.diagnostics.codes
    )


def test_diff_picker_reports_missing_and_degraded_coverage(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    source_path = tmp_path / "src"
    source_path.mkdir()
    module_path = source_path / "module.py"
    module_path.write_text("VALUE = 1\n", encoding="utf-8")
    _commit_all(tmp_path, "baseline")
    module_path.write_text("VALUE = 2\n", encoding="utf-8")
    _commit_all(tmp_path, "change")

    missing_selection = DiffPicker(DatabaseFacade(tmp_path)).pick_candidates(1)
    assert "coverage_missing" in missing_selection.diagnostics.codes

    degraded_database = DatabaseFacade(tmp_path / "degraded")
    degraded_database.project_path.mkdir(parents=True, exist_ok=True)
    _init_repo(degraded_database.project_path)
    degraded_source = degraded_database.project_path / "src"
    degraded_source.mkdir()
    degraded_module = degraded_source / "module.py"
    degraded_module.write_text("VALUE = 1\n", encoding="utf-8")
    _commit_all(degraded_database.project_path, "baseline")
    degraded_module.write_text("VALUE = 2\n", encoding="utf-8")
    _commit_all(degraded_database.project_path, "change")
    _persist_current_coverage(
        degraded_database,
        degraded_database.project_path,
        quality="missing_arcs",
    )

    degraded_selection = DiffPicker(degraded_database).pick_candidates(1)
    assert "coverage_degraded" in degraded_selection.diagnostics.codes


def test_diff_picker_raises_when_requested_history_is_too_short(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    _commit_all(tmp_path, "baseline")

    with pytest.raises(DiffRangeError):
        DiffPicker(DatabaseFacade(tmp_path)).pick_candidates(last_commits=2)
