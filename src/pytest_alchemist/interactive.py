"""Prompt-driven interactive dashboard for pytest-alchemist."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, TypeVar, cast

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich_pyfiglet import RichFiglet

from pytest_alchemist.application import AlchemistApplication, ProjectStatus
from pytest_alchemist.application.models import MinimizerComparison
from pytest_alchemist.diff_picker.models import TestSelection
from pytest_alchemist.diff_picker.picker import DiffRangeError
from pytest_alchemist.test_runner.runner import CoverageFormat

T = TypeVar("T")
ActivityRunner = Callable[[str, Callable[[], T]], T]
ApplicationFactory = Callable[[Path | None], AlchemistApplication]
ReportPrinter = Callable[[str], None]
ComparisonPrinter = Callable[[MinimizerComparison], None]

_CANCELED = object()

ACTION_COLLECT_COVERAGE = "Collect coverage"
ACTION_SELECT_TESTS = "Select affected tests"
ACTION_RUN_MINIMAL = "Run minimal test set"
ACTION_COMPARE_MINIMIZERS = "Compare minimizers"
ACTION_RUN_TESTS = "Run tests"
ACTION_EXIT = "Exit"


def run_dashboard(
    project_path: Path | None = None,
    *,
    console: Console | None = None,
    activity_runner: ActivityRunner | None = None,
    application_factory: ApplicationFactory = AlchemistApplication,
    report_printer: ReportPrinter | None = None,
    comparison_printer: ComparisonPrinter | None = None,
) -> None:
    """Run the interactive dashboard until the user exits or cancels."""

    output = console or Console()
    run_with_activity = activity_runner or _run_immediately
    print_report = report_printer or _print_test_report_summary
    print_comparison = comparison_printer or _print_minimizer_comparison

    try:
        while True:
            application = application_factory(project_path)
            _render_dashboard(output, application.get_project_status())
            action = _ask_action()
            if action in (None, ACTION_EXIT):
                output.print("Goodbye.")
                return

            handled = _run_dashboard_action(
                action=action,
                application=application,
                console=output,
                activity_runner=run_with_activity,
                report_printer=print_report,
                comparison_printer=print_comparison,
            )
            if handled:
                _pause()
    except KeyboardInterrupt:
        output.print("\nGoodbye.")


def _render_dashboard(console: Console, status: ProjectStatus) -> None:
    console.clear()
    console.print(RichFiglet("Pytest Alchemist", colors=["cyan"]))
    console.print(_build_status_panel(status))


def _build_status_panel(status: ProjectStatus) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Project", str(status.project_path))

    if status.latest_coverage_run_uid is None:
        table.add_row("Coverage", "No coverage collected yet")
        table.add_row("Recommended", ACTION_COLLECT_COVERAGE)
    else:
        quality = status.latest_coverage_quality or "unknown"
        completeness = "complete" if quality == "complete" else "degraded"
        table.add_row("Coverage timestamp", _display(status.latest_coverage_created_at))
        table.add_row("Coverage quality", quality)
        table.add_row("Completeness", completeness)
        table.add_row("Coverage run", _display(status.latest_coverage_run_uid))
        table.add_row("Branch", _display(status.git.branch))
        table.add_row("Commit", _short_commit(status.git.commit))
        table.add_row("Dirty when collected", _display_dirty(status.git.is_dirty))

    table.add_row("Latest run", _latest_run_text(status))
    table.add_row("Known tests", str(status.known_test_count))
    table.add_row("Covered entities", str(status.coverage_entity_count))
    table.add_row("Line facts", str(status.coverage_line_fact_count))
    table.add_row("Arc facts", str(status.coverage_arc_fact_count))
    return Panel(table, title="Project status", border_style="cyan")


def _run_dashboard_action(
    *,
    action: str,
    application: AlchemistApplication,
    console: Console,
    activity_runner: ActivityRunner,
    report_printer: ReportPrinter,
    comparison_printer: ComparisonPrinter,
) -> bool:
    console.print()
    try:
        if action == ACTION_COLLECT_COVERAGE:
            result = activity_runner(
                "Collecting coverage with pytest and normalizing facts...",
                application.collect_coverage,
            )
            console.print(
                f"Collected coverage for run {result.run_uid}: "
                f"{result.entity_count} entities, {result.line_fact_count} line facts, "
                f"{result.arc_fact_count} arc facts, quality={result.quality}."
            )
            for warning in result.warnings:
                console.print(f"warning: {warning}")
            return True

        if action == ACTION_SELECT_TESTS:
            diff_options = _ask_diff_options()
            if diff_options is _CANCELED:
                return False
            last_commits, commit_hash = diff_options
            result = activity_runner(
                "Inspecting git changes and matching historical coverage...",
                lambda: application.select_tests(
                    last_commits=last_commits,
                    commit_hash=commit_hash,
                ),
            )
            _print_test_selection(console, result)
            return True

        if action == ACTION_RUN_MINIMAL:
            options = _ask_minimizer_options()
            if options is _CANCELED:
                return False
            last_commits, commit_hash, seed, runtime_tolerance_ms = options
            test_report_path = activity_runner(
                "Selecting, minimizing, and running the affected test set...",
                lambda: application.run_minimal(
                    last_commits=last_commits,
                    commit_hash=commit_hash,
                    seed=seed,
                    runtime_tolerance_ms=runtime_tolerance_ms,
                ),
            )
            report_printer(test_report_path)
            return True

        if action == ACTION_COMPARE_MINIMIZERS:
            options = _ask_minimizer_options()
            if options is _CANCELED:
                return False
            last_commits, commit_hash, seed, runtime_tolerance_ms = options
            comparison = activity_runner(
                "Comparing minimizers against the affected coverage set...",
                lambda: application.compare_minimizers(
                    last_commits=last_commits,
                    commit_hash=commit_hash,
                    seed=seed,
                    runtime_tolerance_ms=runtime_tolerance_ms,
                ),
            )
            comparison_printer(comparison)
            return True

        if action == ACTION_RUN_TESTS:
            options = _ask_run_tests_options()
            if options is _CANCELED:
                return False
            nodeids, coverage_format = options
            message = _run_tests_message(nodeids, coverage_format)
            test_report_path = activity_runner(
                message,
                lambda: application.run_tests(
                    tests=nodeids,
                    collect_coverage=coverage_format,
                    collects_tests=True,
                ),
            )
            report_printer(test_report_path)
            return True

        console.print(f"Unknown action: {action}")
    except DiffRangeError as error:
        console.print(f"error: {error}", style="red")
    except Exception as error:
        console.print(f"error: {error}", style="red")
    return True


def _ask_action() -> str | None:
    return cast(
        str | None,
        questionary.select(
            "Choose an action",
            choices=[
                ACTION_COLLECT_COVERAGE,
                ACTION_SELECT_TESTS,
                ACTION_RUN_MINIMAL,
                ACTION_COMPARE_MINIMIZERS,
                ACTION_RUN_TESTS,
                ACTION_EXIT,
            ],
        ).ask(),
    )


def _ask_diff_options() -> tuple[int | None, str | None] | object:
    mode = questionary.select(
        "Diff mode",
        choices=["Latest commit", "Last N commits", "Specific commit hash"],
        default="Latest commit",
    ).ask()
    if mode is None:
        return _CANCELED
    if mode == "Latest commit":
        return 1, None
    if mode == "Last N commits":
        value = _ask_int("Last commits", default=1, minimum=1)
        if value is _CANCELED:
            return _CANCELED
        return value, None

    commit_hash = _ask_text("Commit hash", validate=_validate_required)
    if commit_hash is _CANCELED:
        return _CANCELED
    return None, commit_hash


def _ask_minimizer_options() -> tuple[int | None, str | None, int | None, int] | object:
    diff_options = _ask_diff_options()
    if diff_options is _CANCELED:
        return _CANCELED
    seed = _ask_optional_int("Seed (optional)")
    if seed is _CANCELED:
        return _CANCELED
    runtime_tolerance_ms = _ask_int("Runtime tolerance in milliseconds", default=10, minimum=0)
    if runtime_tolerance_ms is _CANCELED:
        return _CANCELED
    last_commits, commit_hash = diff_options
    return last_commits, commit_hash, seed, runtime_tolerance_ms


def _ask_run_tests_options() -> tuple[list[str], CoverageFormat | None] | object:
    nodeids_text = _ask_text(
        "Test node ids (optional, separated by spaces)",
        default="",
        validate=lambda _value: True,
    )
    if nodeids_text is _CANCELED:
        return _CANCELED

    coverage_choice = questionary.select(
        "Coverage format",
        choices=["none", "json", "xml", "sqlite"],
        default="none",
    ).ask()
    if coverage_choice is None:
        return _CANCELED
    nodeids = str(nodeids_text).split()
    coverage_format = None if coverage_choice == "none" else cast(CoverageFormat, coverage_choice)
    return nodeids, coverage_format


def _ask_text(
    message: str,
    *,
    default: str = "",
    validate: Callable[[str], bool | str],
) -> str | object:
    value = questionary.text(message, default=default, validate=validate).ask()
    if value is None:
        return _CANCELED
    return str(value).strip()


def _ask_int(message: str, *, default: int, minimum: int) -> int | object:
    value = _ask_text(
        message,
        default=str(default),
        validate=lambda text: _validate_int(text, minimum=minimum, allow_empty=False),
    )
    if value is _CANCELED:
        return _CANCELED
    return int(cast(str, value))


def _ask_optional_int(message: str) -> int | None | object:
    value = _ask_text(
        message,
        default="",
        validate=lambda text: _validate_int(text, minimum=None, allow_empty=True),
    )
    if value is _CANCELED:
        return _CANCELED
    if value == "":
        return None
    return int(cast(str, value))


def _validate_required(value: str) -> bool | str:
    return True if value.strip() else "Enter a value."


def _validate_int(value: str, *, minimum: int | None, allow_empty: bool) -> bool | str:
    if allow_empty and not value.strip():
        return True
    try:
        parsed = int(value)
    except ValueError:
        return "Enter an integer."
    if minimum is not None and parsed < minimum:
        return f"Enter a value greater than or equal to {minimum}."
    return True


def _print_test_selection(console: Console, result: TestSelection) -> None:
    table = Table(title="Affected tests")
    table.add_column("Node id")
    table.add_column("Estimated duration", justify="right")

    for test in result.candidates:
        table.add_row(test.nodeid, f"{test.estimated_duration:.2f}s")

    console.print(table)
    if not result.candidates:
        console.print("No affected tests found.")
    for warning in result.diagnostics.warnings:
        console.print(f"warning: {warning}")


def _print_test_report_summary(test_report_path: str) -> None:
    console = Console()
    report = json.loads(Path(test_report_path).read_text(encoding="utf-8"))
    summary = report["summary"]
    console.print(
        f"Run finished: {summary['passed']} passed, {summary['failed']} failed, "
        f"{summary['skipped']} skipped, exit code {report['exit_code']} "
        f"in {report['duration_seconds']:.3f}s."
    )

    pytest_data = report["pytest"]
    console.print(f"stdout: {pytest_data['stdout_path']}")
    console.print(f"stderr: {pytest_data['stderr_path']}")
    coverage = report.get("coverage")
    if coverage and coverage.get("coverage_json_path"):
        console.print(f"coverage json: {coverage['coverage_json_path']}")
    if coverage and coverage.get("coverage_xml_path"):
        console.print(f"coverage xml: {coverage['coverage_xml_path']}")
    if coverage and coverage.get("coverage_sqlite_path"):
        console.print(f"coverage sqlite: {coverage['coverage_sqlite_path']}")
    console.print(f"test report: {test_report_path}")


def _print_minimizer_comparison(comparison: MinimizerComparison) -> None:
    console = Console()
    console.print(
        "Metrics: Test count, Estimated runtime (ms), Coverage, Uncovered targets"
    )
    table = Table(title="Minimizer comparison")
    table.add_column("Optimizer", no_wrap=True)
    table.add_column("Test count", justify="right", no_wrap=True)
    table.add_column("Estimated runtime (ms)", justify="right", no_wrap=True)
    table.add_column("Coverage", justify="right", no_wrap=True)
    table.add_column("Uncovered targets", justify="right", no_wrap=True)

    for entry in comparison.entries:
        result = entry.result
        table.add_row(
            entry.optimizer_name,
            str(result.selected_test_count),
            f"{result.estimated_runtime * 1000:.2f}",
            f"{result.coverage_percent:.2f}%",
            str(result.uncovered_target_count),
        )

    console.print(table)


def _pause() -> None:
    questionary.press_any_key_to_continue("Press any key to return to the dashboard").ask()


def _run_immediately(message: str, operation: Callable[[], T]) -> T:
    return operation()


def _run_tests_message(nodeids: list[str], coverage_format: CoverageFormat | None) -> str:
    if nodeids:
        message = f"Running {len(nodeids)} selected pytest test(s)..."
    else:
        message = "Running pytest test suite..."
    if coverage_format is not None:
        message = f"{message[:-3]} with {coverage_format} coverage..."
    return message


def _latest_run_text(status: ProjectStatus) -> str:
    if status.latest_run_uid is None:
        return "unknown"
    details = [
        status.latest_run_uid,
        _display(status.latest_run_status),
        _display(status.latest_run_finished_at),
    ]
    return " | ".join(details)


def _display(value: object | None) -> str:
    if value is None or value == "":
        return "unknown"
    return str(value)


def _short_commit(commit: str | None) -> str:
    if not commit:
        return "unknown"
    return commit[:12]


def _display_dirty(is_dirty: bool | None) -> str:
    if is_dirty is None:
        return "unknown"
    return "yes" if is_dirty else "no"
