"""Command line interface for Pytest Alchemist."""

import json
from pathlib import Path
from typing import Any
from typing import cast

import typer
from rich.console import Console
from rich.table import Table

from pytest_alchemist.application import AlchemistApplication
from pytest_alchemist.application.models import MinimizerComparison
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


def _resolve_diff_options(
    last_commits: int | None,
    commit_hash: str | None,
) -> tuple[int | None, str | None]:
    if last_commits is not None and commit_hash is not None:
        raise typer.BadParameter(
            "Choose either --last-commits or --commit-hash, not both."
        )
    if commit_hash is None and last_commits is None:
        return 1, None
    return last_commits, commit_hash


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


def _print_minimizer_comparison(comparison: MinimizerComparison) -> None:
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
    last_commits: int | None = typer.Option(None, "--last-commits", min=1),
    commit_hash: str | None = typer.Option(None, "--commit-hash"),
    project_path: Path | None = typer.Option(None, "--project-path"),
) -> None:
    """Select the full affected test set for recent commits or one commit."""

    last_commits, commit_hash = _resolve_diff_options(last_commits, commit_hash)

    try:
        result = _build_application(project_path).select_tests(
            last_commits=last_commits,
            commit_hash=commit_hash,
        )
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
    last_commits: int | None = typer.Option(None, "--last-commits", min=1),
    commit_hash: str | None = typer.Option(None, "--commit-hash"),
    seed: int | None = typer.Option(None, "--seed"),
    runtime_tolerance_ms: int = typer.Option(
        10,
        "--runtime-tolerance-ms",
        min=0,
    ),
    project_path: Path | None = typer.Option(None, "--project-path"),
) -> None:
    """Select and run a minimized test set for recent commits."""

    last_commits, commit_hash = _resolve_diff_options(last_commits, commit_hash)

    try:
        test_report_path = _build_application(project_path).run_minimal(
            last_commits=last_commits,
            commit_hash=commit_hash,
            seed=seed,
            runtime_tolerance_ms=runtime_tolerance_ms,
        )
    except DiffRangeError as error:
        raise typer.BadParameter(str(error)) from error
    _print_test_report_summary(test_report_path)


@app.command("compare-minimizers")
def compare_minimizers(
    last_commits: int | None = typer.Option(None, "--last-commits", min=1),
    commit_hash: str | None = typer.Option(None, "--commit-hash"),
    seed: int | None = typer.Option(None, "--seed"),
    runtime_tolerance_ms: int = typer.Option(
        10,
        "--runtime-tolerance-ms",
        min=0,
    ),
    project_path: Path | None = typer.Option(None, "--project-path"),
) -> None:
    """Compare greedy and MOPSO minimizers without running tests."""

    last_commits, commit_hash = _resolve_diff_options(last_commits, commit_hash)

    try:
        comparison = _build_application(project_path).compare_minimizers(
            last_commits=last_commits,
            commit_hash=commit_hash,
            seed=seed,
            runtime_tolerance_ms=runtime_tolerance_ms,
        )
    except DiffRangeError as error:
        raise typer.BadParameter(str(error)) from error
    _print_minimizer_comparison(comparison)


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
