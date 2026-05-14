from pathlib import Path

from typer.testing import CliRunner

from pytest_alchemist.cli import app


runner = CliRunner()


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


def _create_minimal_project(project_path: Path) -> None:
    tests_path = project_path / "tests"
    tests_path.mkdir()
    (tests_path / "test_math.py").write_text(
        "\n".join(
            [
                "def test_add():",
                "    assert True",
                "",
                "def test_subtract():",
                "    assert True",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (tests_path / "test_api.py").write_text(
        "\n".join(
            [
                "def test_create_user():",
                "    assert True",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_collect_coverage_command() -> None:
    with runner.isolated_filesystem() as isolated:
        result = runner.invoke(
            app,
            ["collect-coverage", "--project-path", str(Path(isolated))],
        )

    assert result.exit_code == 0
    assert "Collected" in result.output


def test_select_tests_command() -> None:
    with runner.isolated_filesystem() as isolated:
        result = runner.invoke(
            app,
            [
                "select-tests",
                "--last-commits",
                "3",
                "--project-path",
                str(Path(isolated)),
            ],
        )

    assert result.exit_code == 0
    assert "Selected tests" in result.output


def test_run_minimal_command() -> None:
    with runner.isolated_filesystem() as isolated:
        project_path = Path(isolated)
        _create_minimal_project(project_path)

        result = runner.invoke(
            app,
            [
                "run-minimal",
                "--last-commits",
                "3",
                "--project-path",
                str(project_path),
            ],
        )

    assert result.exit_code == 0
    assert "Run finished" in result.output


def test_run_tests_command_runs_all_tests() -> None:
    with runner.isolated_filesystem() as isolated:
        project_path = Path(isolated)
        _create_pytest_project(project_path)

        result = runner.invoke(
            app,
            ["run-tests", "--project-path", str(project_path)],
        )

    assert result.exit_code == 0
    assert "2 passed" in result.output


def test_run_tests_command_runs_selected_nodeid() -> None:
    with runner.isolated_filesystem() as isolated:
        project_path = Path(isolated)
        _create_pytest_project(project_path)

        result = runner.invoke(
            app,
            [
                "run-tests",
                "tests/test_sample.py::test_one",
                "--project-path",
                str(project_path),
            ],
        )

    assert result.exit_code == 0
    assert "1 passed" in result.output


def test_commands_accept_project_path() -> None:
    with runner.isolated_filesystem() as isolated:
        project_path = Path(isolated)

        collect_result = runner.invoke(
            app,
            ["collect-coverage", "--project-path", str(project_path)],
        )
        select_result = runner.invoke(
            app,
            ["select-tests", "--last-commits", "3", "--project-path", str(project_path)],
        )

    assert collect_result.exit_code == 0
    assert select_result.exit_code == 0
