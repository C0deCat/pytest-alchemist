# pytest-alchemist

`pytest-alchemist` is a Python test minimization utility. The goal is to run the
smallest useful subset of tests for recent code changes by combining historical
coverage data, diff analysis, and a minimization algorithm.

The package is currently at the project skeleton stage. The CLI, module
boundaries, and scenario flow exist, but coverage collection, git diff analysis,
SQLite persistence, real pytest execution, and MOPSO minimization are mocked.

## Intended Flow

The planned workflow is:

1. Collect coverage for a project test suite.
2. Store historical coverage and test run data in SQLite.
3. Detect changed code for the latest `N` commits.
4. Find tests that previously covered the changed code.
5. Minimize that candidate set.
6. Run the selected tests.

## Connecting to a User Project

These options describe the preliminary integration contract. Not all behavior is
implemented yet.

### Option 1: Install as a dev dependency

Install `pytest-alchemist` into the target project's development environment and
run commands from the target project root:

```powershell
uv add --dev pytest-alchemist
uv run pytest-alchemist collect-coverage
uv run pytest-alchemist run-minimal --last-commits 3
```

For local development against this repository:

```powershell
uv add --dev "pytest-alchemist @ file:///D:/Personal/repos/pytest-alchemist"
```

Expected future behavior:

- commands use the current working directory as the target project;
- pytest is executed from the target project's environment;
- project data is stored in the target project, for example under
  `.pytest-alchemist/`.

### Option 2: Install from a local editable checkout

From this repository:

```powershell
uv pip install -e .
pytest-alchemist --help
```

This is useful while developing the package itself.

### Option 3: Run against an explicit project path

Future CLI versions may support passing the target project path explicitly:

```powershell
pytest-alchemist run-minimal --project-path D:/path/to/project --last-commits 3
```

Expected future behavior:

- `--project-path` selects the project under analysis;
- pytest, coverage, git diff, and database paths are resolved relative to that
  project;
- this mode can be used from outside the target project directory.

### Option 4: Configure through `pyproject.toml`

Future versions may read settings from the target project's `pyproject.toml`:

```toml
[tool.pytest-alchemist]
test_command = "pytest"
database_path = ".pytest-alchemist/alchemist.db"
```

This would allow projects to define their preferred pytest command, database
location, and minimization settings.

## Commands

Show CLI help:

```powershell
uv run pytest-alchemist --help
```

Collect coverage data:

```powershell
uv run pytest-alchemist collect-coverage
```

Current behavior: returns deterministic mocked coverage data.

Select tests for recent commits:

```powershell
uv run pytest-alchemist select-tests --last-commits 3
```

Current behavior: returns a deterministic mocked minimized test set.

Select and run the minimal test set:

```powershell
uv run pytest-alchemist run-minimal --last-commits 3
```

Current behavior: returns a successful mocked test run result without invoking
pytest.
