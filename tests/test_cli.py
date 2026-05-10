from typer.testing import CliRunner

from pytest_alchemist.cli import app


runner = CliRunner()


def test_collect_coverage_command() -> None:
    result = runner.invoke(app, ["collect-coverage"])

    assert result.exit_code == 0
    assert "Collected" in result.output


def test_select_tests_command() -> None:
    result = runner.invoke(app, ["select-tests", "--last-commits", "3"])

    assert result.exit_code == 0
    assert "Selected tests" in result.output


def test_run_minimal_command() -> None:
    result = runner.invoke(app, ["run-minimal", "--last-commits", "3"])

    assert result.exit_code == 0
    assert "Mock run finished" in result.output
