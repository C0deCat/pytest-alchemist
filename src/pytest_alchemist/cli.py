"""Command line interface for Pytest Alchemist."""

from pathlib import Path
from typing import cast

import typer
from rich.console import Console
from rich.table import Table

from pytest_alchemist.application import AlchemistApplication
from pytest_alchemist.test_runner.runner import CoverageFormat

app = typer.Typer(help="Minimize Python test runs using historical coverage.")
console = Console()


def _build_application(project_path: Path | None = None) -> AlchemistApplication:
    return AlchemistApplication(project_path=project_path)


def _normalize_coverage_format(value: str | None) -> CoverageFormat | None:
    if value is None:
        return None

    normalized = value.lower()
    if normalized not in ("json", "xml"):
        raise typer.BadParameter("collect coverage must be 'json' or 'xml'.")

    return cast(CoverageFormat, normalized)


@app.command("collect-coverage")
def collect_coverage(
    project_path: Path | None = typer.Option(None, "--project-path"),
) -> None:
    """Collect coverage data for the current project."""

    result = _build_application(project_path).collect_coverage()
    console.print(
        f"Collected {len(result.records)} coverage records "
        f"for {len(result.tests)} tests."
    )


@app.command("select-tests")
def select_tests(
    last_commits: int = typer.Option(1, "--last-commits", min=1),
    project_path: Path | None = typer.Option(None, "--project-path"),
) -> None:
    """Select a minimized test set for recent commits."""

    result = _build_application(project_path).select_tests(last_commits)
    table = Table(title="Selected tests")
    table.add_column("Node id")
    table.add_column("Estimated duration", justify="right")

    for test in result.selected_tests:
        table.add_row(test.nodeid, f"{test.estimated_duration:.2f}s")

    console.print(table)
    console.print(result.reason)


@app.command("run-minimal")
def run_minimal(
    last_commits: int = typer.Option(1, "--last-commits", min=1),
    project_path: Path | None = typer.Option(None, "--project-path"),
) -> None:
    """Select and run a minimized test set for recent commits."""

    result = _build_application(project_path).run_minimal(last_commits)
    console.print(
        f"Run finished: {result.passed} passed, {result.failed} failed, "
        f"exit code {result.exit_code} in {result.duration_seconds:.3f}s."
    )


@app.command("run-tests")
def run_tests(
    nodeids: list[str] = typer.Argument(None),
    project_path: Path | None = typer.Option(None, "--project-path"),
    collect_coverage: str | None = typer.Option(None, "--collect-coverage"),
) -> None:
    """Run pytest tests in the target project."""

    result = _build_application(project_path).run_tests(
        tests=nodeids,
        collect_coverage=_normalize_coverage_format(collect_coverage),
    )
    console.print(
        f"Run finished: {result.passed} passed, {result.failed} failed, "
        f"exit code {result.exit_code} in {result.duration_seconds:.3f}s."
    )

    if result.stdout_path:
        console.print(f"stdout: {result.stdout_path}")
    if result.stderr_path:
        console.print(f"stderr: {result.stderr_path}")
    if result.coverage and result.coverage.coverage_json_path:
        console.print(f"coverage json: {result.coverage.coverage_json_path}")
    if result.coverage and result.coverage.coverage_xml_path:
        console.print(f"coverage xml: {result.coverage.coverage_xml_path}")
