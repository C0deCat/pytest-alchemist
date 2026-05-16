# pytest-alchemist

`pytest-alchemist` is a Python test minimization utility. The goal is to run the
smallest useful subset of tests for recent code changes by combining historical
coverage data, diff analysis, and a minimization algorithm.

The package is currently at the project skeleton stage. The CLI, module
boundaries, and scenario flow exist, while some analysis and minimization
features are still mocked.

## Intended Flow

The planned workflow is:

1. Collect coverage for a project test suite.
2. Store historical coverage and test run data.
3. Detect changed code for the latest `N` commits.
4. Find tests that previously covered the changed code.
5. Minimize that candidate set.
6. Run the selected tests.

## Usage

The primary usage model is to install `pytest-alchemist` as a dev dependency of
the target project and run commands from that project's development environment.

```powershell
uv add --dev pytest-alchemist
uv run pytest-alchemist collect-coverage
uv run pytest-alchemist run-minimal --last-commits 3
```

For local development against this repository:

```powershell
uv add --dev "pytest-alchemist @ file:///D:/Personal/repos/pytest-alchemist"
```

By default, commands use the current working directory as the target project.
Use `--project-path` only when you need to override that default:

```powershell
uv run pytest-alchemist run-tests --project-path D:/path/to/project
```

Project data is stored under the target project root in:

```text
.pytest-alchemist-artifacts/
```

## Commands

Show CLI help:

```powershell
uv run pytest-alchemist --help
```

Collect coverage data:

```powershell
uv run pytest-alchemist collect-coverage
```

Select tests for recent commits:

```powershell
uv run pytest-alchemist select-tests --last-commits 3
```

Select tests for one explicit commit:

```powershell
uv run pytest-alchemist select-tests --commit-hash abc1234
```

Select and run the minimal test set:

```powershell
uv run pytest-alchemist run-minimal --last-commits 3
```

Run pytest through `pytest-alchemist`:

```powershell
uv run pytest-alchemist run-tests
uv run pytest-alchemist run-tests tests/test_api.py::test_create_user
uv run pytest-alchemist run-tests --collect-coverage json
```
