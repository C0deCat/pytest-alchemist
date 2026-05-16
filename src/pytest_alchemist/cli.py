"""Command line interface for Pytest Alchemist."""

import json
from pathlib import Path
from typing import Any
from typing import cast

import typer
from rich.console import Console
from rich.table import Table

from pytest_alchemist.application import AlchemistApplication
from pytest_alchemist.diff_picker.picker import DiffRangeError
from pytest_alchemist.test_runner.runner import CoverageFormat

app = typer.Typer(help="Minimize Python test runs using historical coverage.")
console = Console()


def _build_application(project_path: Path | None = None) -> AlchemistApplication:
    return AlchemistApplication(project_path=project_path)


def _normalize_coverage_format(value: str | None) -> CoverageFormat | None:
    if value is None:
        return None

    normalized = value.lower()
    if normalized not in ("json", "xml", "sqlite"):
        raise typer.BadParameter("collect coverage must be 'json', 'xml', or 'sqlite'.")

    return cast(CoverageFormat, normalized)


def _load_test_report(test_report_path: str) -> dict[str, Any]:
    return json.loads(Path(test_report_path).read_text(encoding="utf-8"))


def _print_test_report_summary(test_report_path: str) -> None:
    report = _load_test_report(test_report_path)
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


@app.command("collect-coverage")
def collect_coverage(
    project_path: Path | None = typer.Option(None, "--project-path"),
) -> None:
    """Collect coverage data for the current project."""

    result = _build_application(project_path).collect_coverage()
    console.print(
        f"Collected coverage for run {result.run_uid}: "
        f"{result.entity_count} entities, {result.line_fact_count} line facts, "
        f"{result.arc_fact_count} arc facts, quality={result.quality}."
    )
    for warning in result.warnings:
        console.print(f"warning: {warning}")


@app.command("select-tests")
def select_tests(
    last_commits: int = typer.Option(1, "--last-commits", min=1),
    project_path: Path | None = typer.Option(None, "--project-path"),
) -> None:
    """Select the full affected test set for recent commits."""

    try:
        result = _build_application(project_path).select_tests(last_commits)
    except DiffRangeError as error:
        raise typer.BadParameter(str(error)) from error

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


@app.command("run-minimal")
def run_minimal(
    last_commits: int = typer.Option(1, "--last-commits", min=1),
    project_path: Path | None = typer.Option(None, "--project-path"),
) -> None:
    """Select and run a minimized test set for recent commits."""

    test_report_path = _build_application(project_path).run_minimal(last_commits)
    _print_test_report_summary(test_report_path)


@app.command("run-tests")
def run_tests(
    nodeids: list[str] = typer.Argument(None),
    project_path: Path | None = typer.Option(None, "--project-path"),
    collect_coverage: str | None = typer.Option(None, "--collect-coverage"),
    collects_tests: bool = typer.Option(True, "--collect-tests/--no-collect-tests"),
) -> None:
    """Run pytest tests in the target project."""

    test_report_path = _build_application(project_path).run_tests(
        tests=nodeids,
        collect_coverage=_normalize_coverage_format(collect_coverage),
        collects_tests=collects_tests,
    )
    _print_test_report_summary(test_report_path)
