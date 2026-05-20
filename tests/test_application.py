import json
import sqlite3
from pathlib import Path

from pytest_alchemist.application import AlchemistApplication
from pytest_alchemist.coverage_analysis.models import (
    CoverageArcFact,
    CoverageArtifactMetadata,
    CoverageEntity,
    CoverageLineFact,
    CoverageRecord,
)
from pytest_alchemist.database.facade import DatabaseFacade
from pytest_alchemist.diff_picker.models import (
    ChangedCode,
    MatchEvidence,
    SelectionDiagnostics,
    TestSelection,
)
from pytest_alchemist.minimizer import Minimizer
from pytest_alchemist.minimizer.models import MinimizationInput
from pytest_alchemist.test_runner.models import TestCase
from pytest_alchemist.test_runner.runner import ARTIFACTS_DIR_NAME


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


def _write_test_report(
    project_path: Path,
    *,
    uid: str,
    selected_tests: list[TestCase | str] | None = None,
) -> str:
    selected_nodeids = [
        test.nodeid if isinstance(test, TestCase) else test
        for test in list(selected_tests or [])
    ]
    run_dir = project_path / ARTIFACTS_DIR_NAME / "test-runs" / uid
    run_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = run_dir / "stdout.txt"
    stderr_path = run_dir / "stderr.txt"
    stdout_path.write_text("", encoding="utf-8")
    stderr_path.write_text("", encoding="utf-8")
    runned_tests = {
        nodeid: {
            "nodeid": nodeid,
            "outcome": "passed",
            "duration_ms": 10,
        }
        for nodeid in selected_nodeids
    }
    report_path = run_dir / "test_report.json"
    report = {
        "schema_version": 1,
        "uid": uid,
        "project_root": str(project_path),
        "started_at": "2026-05-13T01:00:00Z",
        "finished_at": "2026-05-13T01:00:01Z",
        "duration_seconds": 0.01,
        "exit_code": 0,
        "status": "passed",
        "pytest": {
            "args": ["python", "-m", "pytest", *selected_nodeids],
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        },
        "selection": {
            "selected_tests": selected_nodeids,
        },
        "summary": {
            "passed": len(selected_nodeids),
            "failed": 0,
            "skipped": 0,
            "total": len(selected_nodeids),
        },
        "runned_tests": runned_tests,
        "coverage": None,
        "artifacts": {
            "run_dir": str(run_dir),
            "test_report_path": str(report_path),
        },
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return str(report_path)


class _FakeDiffPicker:
    def __init__(self, selection: TestSelection) -> None:
        self.selection = selection
        self.last_commits: int | None = None
        self.commit_hash: str | None = None

    def pick_candidates(
        self,
        last_commits: int | None = None,
        commit_hash: str | None = None,
    ) -> TestSelection:
        self.last_commits = last_commits
        self.commit_hash = commit_hash
        return self.selection


def _selection() -> TestSelection:
    candidates = [
        TestCase(
            nodeid="tests/test_sample.py::test_one",
            file_path="tests/test_sample.py",
            estimated_duration=0.02,
        ),
        TestCase(
            nodeid="tests/test_sample.py::test_two",
            file_path="tests/test_sample.py",
            estimated_duration=0.01,
        ),
    ]
    return TestSelection(
        candidates=candidates,
        target_changes=[
            ChangedCode(
                file_path="src/sample.py",
                added_lines=[],
                modified_lines=[2],
                deleted_lines=[],
            )
        ],
        coverage_records=[
            CoverageRecord(
                test_nodeid="tests/test_sample.py::test_one",
                file_path="src/sample.py",
                lines=[2],
            ),
            CoverageRecord(
                test_nodeid="tests/test_sample.py::test_two",
                file_path="src/sample.py",
                lines=[2],
            ),
        ],
        evidence=[
            MatchEvidence(
                test_nodeid="tests/test_sample.py::test_one",
                file_path="src/sample.py",
                line=2,
                change_kind="modified",
                match_kind="raw_line",
            )
        ],
        diagnostics=SelectionDiagnostics(
            codes=[],
            warnings=[],
            coverage_quality="complete",
        ),
    )


def test_collect_coverage_runs_pytest_and_normalizes_coverage(tmp_path: Path) -> None:
    _create_pytest_project(tmp_path)
    app = AlchemistApplication(project_path=tmp_path)

    result = app.collect_coverage()

    assert result.run_uid
    assert result.quality == "complete"
    assert result.entity_count > 0
    assert result.line_fact_count > 0
    assert result.arc_fact_count > 0


def test_select_tests_returns_full_affected_set(tmp_path: Path) -> None:
    diff_picker = _FakeDiffPicker(_selection())
    app = AlchemistApplication(
        project_path=tmp_path,
        diff_picker=diff_picker,
    )

    result = app.select_tests(last_commits=3)

    assert [test.nodeid for test in result.candidates] == [
        "tests/test_sample.py::test_one",
        "tests/test_sample.py::test_two",
    ]
    assert diff_picker.last_commits == 3
    assert diff_picker.commit_hash is None


def test_select_tests_forwards_commit_hash(tmp_path: Path) -> None:
    diff_picker = _FakeDiffPicker(_selection())
    app = AlchemistApplication(project_path=tmp_path, diff_picker=diff_picker)

    app.select_tests(commit_hash="abc123")

    assert diff_picker.last_commits is None
    assert diff_picker.commit_hash == "abc123"


def test_run_minimal_forwards_commit_hash(tmp_path: Path) -> None:
    diff_picker = _FakeDiffPicker(_selection())

    def fake_run_tests(
        project_path: str,
        tests: list[TestCase | str] | None,
        collect_coverage: object,
        collects_tests: bool,
    ) -> str:
        return _write_test_report(Path(project_path), uid="run-minimal", selected_tests=tests)

    app = AlchemistApplication(
        project_path=tmp_path,
        diff_picker=diff_picker,
        run_tests_func=fake_run_tests,
    )

    app.run_minimal(commit_hash="abc123")

    assert diff_picker.last_commits is None
    assert diff_picker.commit_hash == "abc123"


def test_run_minimal_returns_successful_mock_result(tmp_path: Path) -> None:
    def fake_run_tests(
        project_path: str,
        tests: list[TestCase | str] | None,
        collect_coverage: object,
        collects_tests: bool,
    ) -> str:
        return _write_test_report(Path(project_path), uid="run-minimal", selected_tests=tests)

    app = AlchemistApplication(
        project_path=tmp_path,
        diff_picker=_FakeDiffPicker(_selection()),
        run_tests_func=fake_run_tests,
    )

    test_report_path = app.run_minimal(last_commits=3)
    report = json.loads(Path(test_report_path).read_text(encoding="utf-8"))

    assert report["exit_code"] == 0
    assert report["summary"]["failed"] == 0
    assert report["summary"]["passed"] == len(report["selection"]["selected_tests"])


def test_application_defaults_project_path_to_cwd(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    app = AlchemistApplication()

    assert app.project_path == tmp_path.resolve()


def test_application_accepts_explicit_project_path(tmp_path: Path) -> None:
    app = AlchemistApplication(project_path=tmp_path)

    assert app.project_path == tmp_path.resolve()


def test_get_project_status_returns_latest_coverage_state(tmp_path: Path) -> None:
    database = DatabaseFacade(project_path=tmp_path)
    report_path = _write_test_report(
        tmp_path,
        uid="run-status",
        selected_tests=["tests/test_sample.py::test_one"],
    )
    database.save_test_run(report_path)
    database.save_coverage_artifact_metadata(
        CoverageArtifactMetadata(
            run_uid="run-status",
            path=str(Path(report_path).parent / ".coverage"),
            sha256="abc",
            coverage_py_version="7.13.5",
            has_contexts=True,
            has_arcs=True,
            quality="complete",
        )
    )
    database.replace_coverage_facts(
        "run-status",
        [
            CoverageEntity(
                id=1,
                file_path="sample.py",
                module_name="sample",
                qualified_name="sample",
                kind="module",
                start_line=1,
                end_line=3,
                normalized_hash="hash",
                current_revision=1,
                parent_id=None,
            )
        ],
        [
            CoverageLineFact(
                nodeid="tests/test_sample.py::test_one",
                phase="run",
                entity_id=1,
                raw_line=1,
                entity_line_offset=0,
            )
        ],
        [
            CoverageArcFact(
                nodeid="tests/test_sample.py::test_one",
                phase="run",
                entity_id=1,
                from_line=1,
                to_line=2,
                from_offset=0,
                to_offset=1,
                arc_hash="arc",
            )
        ],
    )

    status = AlchemistApplication(project_path=tmp_path, database=database).get_project_status()

    assert status.project_path == tmp_path.resolve()
    assert status.latest_coverage_run_uid == "run-status"
    assert status.latest_coverage_quality == "complete"
    assert status.latest_run_uid == "run-status"
    assert status.latest_run_status == "passed"
    assert status.coverage_entity_count == 1
    assert status.coverage_line_fact_count == 1
    assert status.coverage_arc_fact_count == 1
    assert status.known_test_count == 1
    assert status.git.branch is None
    assert status.git.commit is None
    assert status.git.is_dirty is None


def test_run_minimal_passes_project_path_to_runner(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run_tests(
        project_path: str,
        tests: list[TestCase | str] | None,
        collect_coverage: object,
        collects_tests: bool,
    ) -> str:
        captured["project_path"] = project_path
        captured["tests"] = tests
        captured["collect_coverage"] = collect_coverage
        captured["collects_tests"] = collects_tests
        return _write_test_report(Path(project_path), uid="run-minimal", selected_tests=tests)

    app = AlchemistApplication(
        project_path=tmp_path,
        diff_picker=_FakeDiffPicker(_selection()),
        run_tests_func=fake_run_tests,
    )

    test_report_path = app.run_minimal(last_commits=3)
    report = json.loads(Path(test_report_path).read_text(encoding="utf-8"))

    assert captured["project_path"] == str(tmp_path.resolve())
    assert [
        test.nodeid if isinstance(test, TestCase) else test
        for test in captured["tests"]
    ] == report["selection"]["selected_tests"]
    assert captured["collect_coverage"] is None
    assert captured["collects_tests"] is True


def test_run_minimal_forwards_minimizer_parameters(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class _FakeMinimizer:
        def minimize(
            self,
            input_data: MinimizationInput,
            seed: int | None = None,
            runtime_tolerance_ms: int = 10,
        ):
            captured["input_data"] = input_data
            captured["seed"] = seed
            captured["runtime_tolerance_ms"] = runtime_tolerance_ms
            return Minimizer().minimize(
                input_data,
                seed=seed,
                runtime_tolerance_ms=runtime_tolerance_ms,
            )

    def fake_run_tests(
        project_path: str,
        tests: list[TestCase | str] | None,
        collect_coverage: object,
        collects_tests: bool,
    ) -> str:
        return _write_test_report(Path(project_path), uid="run-minimal", selected_tests=tests)

    app = AlchemistApplication(
        project_path=tmp_path,
        diff_picker=_FakeDiffPicker(_selection()),
        minimizer=_FakeMinimizer(),
        run_tests_func=fake_run_tests,
    )

    app.run_minimal(last_commits=3, seed=123, runtime_tolerance_ms=25)

    assert captured["seed"] == 123
    assert captured["runtime_tolerance_ms"] == 25


def test_compare_minimizers_returns_greedy_and_mopso_results(tmp_path: Path) -> None:
    diff_picker = _FakeDiffPicker(_selection())
    app = AlchemistApplication(project_path=tmp_path, diff_picker=diff_picker)

    comparison = app.compare_minimizers(commit_hash="abc123", seed=123)

    assert diff_picker.last_commits is None
    assert diff_picker.commit_hash == "abc123"
    assert [entry.optimizer_name for entry in comparison.entries] == ["Greedy", "MOPSO"]
    assert [entry.result.selected_test_count for entry in comparison.entries] == [1, 1]
    assert all(entry.result.coverage_percent == 100.0 for entry in comparison.entries)


def test_run_tests_persists_run_and_coverage_artifact(tmp_path: Path) -> None:
    _create_pytest_project(tmp_path)
    app = AlchemistApplication(project_path=tmp_path)

    test_report_path = app.run_tests(collect_coverage="json")
    report = json.loads(Path(test_report_path).read_text(encoding="utf-8"))

    database_path = tmp_path / ARTIFACTS_DIR_NAME / "pytest-alchemist.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        run = connection.execute(
            "SELECT uid, coverage_enabled FROM test_runs WHERE uid = ?",
            (report["uid"],),
        ).fetchone()
        artifacts = connection.execute(
            "SELECT run_uid, format, path FROM coverage_artifacts WHERE run_uid = ?",
            (report["uid"],),
        ).fetchall()
        test = connection.execute(
            """
            SELECT last_seen_run_uid, nodeid, last_outcome
            FROM tests
            WHERE last_seen_run_uid = ?
            """,
            (report["uid"],),
        ).fetchone()

    assert report["exit_code"] == 0
    assert run is not None
    assert run["uid"] == report["uid"]
    assert run["coverage_enabled"] == 1
    artifacts_by_format = {artifact["format"]: artifact for artifact in artifacts}
    assert set(artifacts_by_format) == {"json", "sqlite"}
    assert artifacts_by_format["json"]["run_uid"] == report["uid"]
    assert Path(artifacts_by_format["json"]["path"]).exists()
    assert artifacts_by_format["sqlite"]["run_uid"] == report["uid"]
    assert Path(artifacts_by_format["sqlite"]["path"]).exists()
    assert test is not None
    assert test["last_seen_run_uid"] == report["uid"]
    assert test["last_outcome"] == "passed"


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

    assert result.selected_tests == []
