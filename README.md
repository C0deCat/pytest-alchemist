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
uv run pytest-alchemist compare-minimizers --last-commits 3
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

## Project Configuration

`pytest-alchemist` needs per-test coverage facts. It runs pytest through
`pytest-cov` with `--cov-context=test`, `--cov-branch`, and an internal pytest
plugin that records test node ids and durations. For best results, keep the
target project's coverage settings compatible with those requirements:

```toml
[tool.coverage.run]
relative_files = true
branch = true
source = ["your_package"]
```

Include test files only when you intentionally want to track test-file coverage.
For the usual "which tests are affected by production code changes?" workflow,
covering the production package keeps the coverage index smaller and easier to
reason about. In pure-Python projects with many tests traversing the same core
modules, high line and arc fact counts can still be normal even with a focused
`source` setting.

If your project already uses `pytest-cov`, `pytest-alchemist` will reuse the
project coverage config it finds in `pyproject.toml`, `.coveragerc`, `tox.ini`,
or `setup.cfg`. Avoid mixing old statement-only `.coverage` files with a new
branch coverage run. In particular, `parallel = true` can leave
`.coverage.*` worker files behind when pytest-cov cannot combine artifacts.
`pytest-alchemist` CAN falls back to the best readable `.coverage.*` file with
pytest contexts and branch arcs, but a clean alchemist run is still easier to
reason about.

Recommended setup loop:

```powershell
uv run pytest-alchemist collect-coverage
uv run pytest-alchemist select-tests --last-commits 3
uv run pytest-alchemist run-minimal --last-commits 3
```

`collect-coverage` should report `quality=complete`. `select-tests` returns the
full affected test set from historical coverage. `run-minimal` then minimizes
that candidate set and runs only the selected node ids.

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

Select and run the minimal test set for one explicit commit:

```powershell
uv run pytest-alchemist run-minimal --commit-hash abc1234
```

Compare greedy and MOPSO minimizers without running the selected tests:

```powershell
uv run pytest-alchemist compare-minimizers --last-commits 3
uv run pytest-alchemist compare-minimizers --commit-hash abc1234 --seed 123
```

The comparison reports selected test count, estimated runtime in milliseconds,
coverage percent, and uncovered target count for each optimizer.

Run pytest through `pytest-alchemist`:

```powershell
uv run pytest-alchemist run-tests
uv run pytest-alchemist run-tests tests/test_api.py::test_create_user
uv run pytest-alchemist run-tests --collect-coverage json
```

## Troubleshooting

If `collect-coverage` reports `quality=missing_contexts`, the coverage artifact
that was normalized did not contain pytest-cov test contexts. Make sure the run
goes through `pytest-alchemist collect-coverage` or otherwise uses
`--cov-context=test`.

If you see `coverage.exceptions.DataError: Can't combine branch coverage data
with statement data`, pytest-cov tried to combine incompatible artifacts. Remove
stale coverage artifacts from the target project, or run with a coverage config
that does not force incompatible `parallel` output for the alchemist pass.
When pytest-cov leaves a good `.coverage.*` worker artifact, `pytest-alchemist`
will prefer that artifact over a degraded base `.coverage` file.

If `select-tests --last-commits N` finds no tests, first check whether the
requested range contains Python changes. Use `--commit-hash HASH` for an
explicit commit when recent commits are release notes, docs, or other non-Python
changes.

Selection currently matches changed current-side line numbers to previously
covered line numbers. Deleted lines, comments, decorator-only changes, stale line
numbers from old commits, and changed lines that were not executed in the latest
coverage run may produce no candidates. In that case, collect fresh coverage or
select a commit/range whose changed executable lines overlap the current
coverage facts.
