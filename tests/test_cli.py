from pathlib import Path
import subprocess

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


def _git(project_path: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=project_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _create_git_history(project_path: Path) -> None:
    _git(project_path, "init")
    _git(project_path, "config", "user.email", "tests@example.com")
    _git(project_path, "config", "user.name", "Tests")
    module_path = project_path / "module.py"
    module_path.write_text("VALUE = 1\n", encoding="utf-8")
    _git(project_path, "add", ".")
    _git(project_path, "commit", "-m", "baseline")
    module_path.write_text("VALUE = 2\n", encoding="utf-8")
    _git(project_path, "add", ".")
    _git(project_path, "commit", "-m", "change")


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
        project_path = Path(isolated)
        _create_git_history(project_path)
        result = runner.invoke(
            app,
            [
                "select-tests",
                "--last-commits",
                "1",
                "--project-path",
                str(project_path),
            ],
        )

    assert result.exit_code == 0
    assert "Affected tests" in result.output
    assert "coverage data is available" in result.output


def test_select_tests_command_accepts_commit_hash() -> None:
    with runner.isolated_filesystem() as isolated:
        project_path = Path(isolated)
        _create_git_history(project_path)
        commit_hash = _git(project_path, "rev-parse", "HEAD")
        result = runner.invoke(
            app,
            [
                "select-tests",
                "--commit-hash",
                commit_hash,
                "--project-path",
                str(project_path),
            ],
        )

    assert result.exit_code == 0
    assert "Affected tests" in result.output


def test_select_tests_command_rejects_multiple_diff_modes() -> None:
    with runner.isolated_filesystem() as isolated:
        project_path = Path(isolated)
        _create_git_history(project_path)
        commit_hash = _git(project_path, "rev-parse", "HEAD")
        result = runner.invoke(
            app,
            [
                "select-tests",
                "--last-commits",
                "1",
                "--commit-hash",
                commit_hash,
                "--project-path",
                str(project_path),
            ],
        )

    assert result.exit_code != 0
    assert "Choose either --last-commits or --commit-hash" in result.output


def test_select_tests_command_defaults_to_last_commit() -> None:
    with runner.isolated_filesystem() as isolated:
        project_path = Path(isolated)
        _create_git_history(project_path)
        result = runner.invoke(
            app,
            ["select-tests", "--project-path", str(project_path)],
        )

    assert result.exit_code == 0
    assert "Affected tests" in result.output


def test_run_minimal_command() -> None:
    with runner.isolated_filesystem() as isolated:
        project_path = Path(isolated)
        _create_minimal_project(project_path)
        _create_git_history(project_path)

        result = runner.invoke(
            app,
            [
                "run-minimal",
                "--last-commits",
                "1",
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
        _create_git_history(project_path)

        collect_result = runner.invoke(
            app,
            ["collect-coverage", "--project-path", str(project_path)],
        )
        select_result = runner.invoke(
            app,
            ["select-tests", "--last-commits", "1", "--project-path", str(project_path)],
        )

    assert collect_result.exit_code == 0
    assert select_result.exit_code == 0
