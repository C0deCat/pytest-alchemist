import io
from pathlib import Path
from typing import Callable

from rich.console import Console

from pytest_alchemist.application.models import GitSnapshot, ProjectStatus
from pytest_alchemist.coverage_analysis.models import CoverageRecord
from pytest_alchemist.diff_picker.models import (
    ChangedCode,
    SelectionDiagnostics,
    TestSelection,
)
from pytest_alchemist.interactive import (
    ACTION_EXIT,
    ACTION_RUN_MINIMAL,
    ACTION_SELECT_TESTS,
    run_dashboard,
)
from pytest_alchemist.test_runner.models import TestCase


class _Question:
    def __init__(self, answers: list[object]) -> None:
        self._answers = answers

    def ask(self) -> object:
        return self._answers.pop(0)


class _FakeApplication:
    def __init__(self, project_path: Path) -> None:
        self.project_path = project_path
        self.select_calls: list[dict[str, object]] = []
        self.run_minimal_calls: list[dict[str, object]] = []

    def get_project_status(self) -> ProjectStatus:
        return ProjectStatus(
            project_path=self.project_path,
            latest_coverage_run_uid=None,
            latest_coverage_created_at=None,
            latest_coverage_quality=None,
            latest_run_uid=None,
            latest_run_finished_at=None,
            latest_run_status=None,
            coverage_entity_count=0,
            coverage_line_fact_count=0,
            coverage_arc_fact_count=0,
            known_test_count=0,
            git=GitSnapshot(branch=None, commit=None, is_dirty=None),
        )

    def select_tests(
        self,
        last_commits: int | None = None,
        commit_hash: str | None = None,
    ) -> TestSelection:
        self.select_calls.append(
            {"last_commits": last_commits, "commit_hash": commit_hash}
        )
        return TestSelection(
            candidates=[
                TestCase(
                    nodeid="tests/test_sample.py::test_one",
                    file_path="tests/test_sample.py",
                    estimated_duration=0.1,
                )
            ],
            target_changes=[
                ChangedCode(
                    file_path="sample.py",
                    added_lines=[],
                    modified_lines=[1],
                    deleted_lines=[],
                )
            ],
            coverage_records=[
                CoverageRecord(
                    test_nodeid="tests/test_sample.py::test_one",
                    file_path="sample.py",
                    lines=[1],
                )
            ],
            evidence=[],
            diagnostics=SelectionDiagnostics(
                codes=[],
                warnings=[],
                coverage_quality="complete",
            ),
        )

    def run_minimal(
        self,
        last_commits: int | None = None,
        commit_hash: str | None = None,
        seed: int | None = None,
        runtime_tolerance_ms: int = 10,
    ) -> str:
        self.run_minimal_calls.append(
            {
                "last_commits": last_commits,
                "commit_hash": commit_hash,
                "seed": seed,
                "runtime_tolerance_ms": runtime_tolerance_ms,
            }
        )
        return "report.json"


def _console() -> tuple[Console, io.StringIO]:
    stream = io.StringIO()
    return Console(file=stream, width=120, force_terminal=False), stream


def _immediate_activity(message: str, operation: Callable[[], object]) -> object:
    return operation()


def test_dashboard_renders_empty_status_and_exits(monkeypatch, tmp_path: Path) -> None:
    selects = [ACTION_EXIT]
    monkeypatch.setattr(
        "pytest_alchemist.interactive.questionary.select",
        lambda *args, **kwargs: _Question(selects),
    )
    console, stream = _console()

    run_dashboard(
        project_path=tmp_path,
        console=console,
        activity_runner=_immediate_activity,
        application_factory=lambda project_path: _FakeApplication(project_path or tmp_path),
    )

    output = stream.getvalue()
    assert "No coverage collected yet" in output
    assert "Goodbye." in output


def test_dashboard_select_tests_uses_guided_diff_prompt(
    monkeypatch,
    tmp_path: Path,
) -> None:
    application = _FakeApplication(tmp_path)
    selects = [ACTION_SELECT_TESTS, "Last N commits", ACTION_EXIT]
    texts = ["3"]
    monkeypatch.setattr(
        "pytest_alchemist.interactive.questionary.select",
        lambda *args, **kwargs: _Question(selects),
    )
    monkeypatch.setattr(
        "pytest_alchemist.interactive.questionary.text",
        lambda *args, **kwargs: _Question(texts),
    )
    monkeypatch.setattr(
        "pytest_alchemist.interactive.questionary.press_any_key_to_continue",
        lambda *args, **kwargs: _Question([None]),
    )
    console, stream = _console()

    run_dashboard(
        project_path=tmp_path,
        console=console,
        activity_runner=_immediate_activity,
        application_factory=lambda _project_path: application,
    )

    assert application.select_calls == [{"last_commits": 3, "commit_hash": None}]
    assert "Affected tests" in stream.getvalue()


def test_dashboard_canceled_prompt_returns_to_menu(monkeypatch, tmp_path: Path) -> None:
    application = _FakeApplication(tmp_path)
    selects = [ACTION_SELECT_TESTS, None, ACTION_EXIT]
    monkeypatch.setattr(
        "pytest_alchemist.interactive.questionary.select",
        lambda *args, **kwargs: _Question(selects),
    )
    console, _stream = _console()

    run_dashboard(
        project_path=tmp_path,
        console=console,
        activity_runner=_immediate_activity,
        application_factory=lambda _project_path: application,
    )

    assert application.select_calls == []


def test_dashboard_run_minimal_collects_parameters(monkeypatch, tmp_path: Path) -> None:
    application = _FakeApplication(tmp_path)
    selects = [ACTION_RUN_MINIMAL, "Specific commit hash", ACTION_EXIT]
    texts = ["abc123", "123", "25"]
    report_paths: list[str] = []
    monkeypatch.setattr(
        "pytest_alchemist.interactive.questionary.select",
        lambda *args, **kwargs: _Question(selects),
    )
    monkeypatch.setattr(
        "pytest_alchemist.interactive.questionary.text",
        lambda *args, **kwargs: _Question(texts),
    )
    monkeypatch.setattr(
        "pytest_alchemist.interactive.questionary.press_any_key_to_continue",
        lambda *args, **kwargs: _Question([None]),
    )
    console, _stream = _console()

    run_dashboard(
        project_path=tmp_path,
        console=console,
        activity_runner=_immediate_activity,
        application_factory=lambda _project_path: application,
        report_printer=report_paths.append,
    )

    assert application.run_minimal_calls == [
        {
            "last_commits": None,
            "commit_hash": "abc123",
            "seed": 123,
            "runtime_tolerance_ms": 25,
        }
    ]
    assert report_paths == ["report.json"]
