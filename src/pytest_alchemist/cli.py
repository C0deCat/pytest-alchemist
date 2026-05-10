"""Command line interface for Pytest Alchemist."""

import typer
from rich.console import Console
from rich.table import Table

from pytest_alchemist.application import AlchemistApplication

app = typer.Typer(help="Minimize Python test runs using historical coverage.")
console = Console()


def _build_application() -> AlchemistApplication:
    return AlchemistApplication()


@app.command("collect-coverage")
def collect_coverage() -> None:
    """Collect coverage data for the current project."""

    result = _build_application().collect_coverage()
    console.print(
        f"Collected {len(result.records)} coverage records "
        f"for {len(result.tests)} tests."
    )


@app.command("select-tests")
def select_tests(
    last_commits: int = typer.Option(1, "--last-commits", min=1),
) -> None:
    """Select a minimized test set for recent commits."""

    result = _build_application().select_tests(last_commits)
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
) -> None:
    """Select and run a minimized test set for recent commits."""

    result = _build_application().run_minimal(last_commits)
    console.print(
        f"Mock run finished: {result.passed} passed, {result.failed} failed, "
        f"exit code {result.exit_code}."
    )
