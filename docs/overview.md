# Project Overview

`pytest-alchemist` is organized around a small orchestration layer and several
focused modules. The current implementation is a deterministic mock skeleton:
module boundaries and data flow are in place, while real pytest execution,
coverage parsing, SQLite persistence, git diff analysis, and MOPSO minimization
are still planned.

## Module Responsibilities

### `pytest_alchemist.cli`

Owns the command line interface. It translates user commands and options into
application scenarios and renders results for the terminal.

Current commands:

- `collect-coverage`
- `select-tests --last-commits N`
- `run-minimal --last-commits N`
- `run-tests [NODEID...]`

Dependencies:

- `application`

### `pytest_alchemist.application`

Owns high-level use cases and coordinates lower-level modules. This layer is the
main orchestration boundary for scenarios such as collecting coverage, selecting
tests for recent changes, and running the selected minimal set.

Responsibilities:

- create or receive service instances;
- call `diff_picker` to find candidate tests;
- call `minimizer` to reduce the candidate set;
- call `test_runner` to run selected tests;
- ask `database` to store scenario results when needed.

Dependencies:

- `coverage_analysis`
- `database`
- `diff_picker`
- `minimizer`
- `test_runner`

### `pytest_alchemist.test_runner`

Owns test execution infrastructure. In the current skeleton it returns a mocked
successful result instead of invoking pytest.

Future responsibilities:

- execute pytest in the target project environment;
- run a selected list of pytest node ids;
- capture exit code, duration, passed and failed counts, and output artifacts.

Dependencies:

- none

### `pytest_alchemist.coverage_analysis`

Owns coverage collection and coverage data interpretation. In the current
skeleton it returns deterministic mocked coverage records from the database
facade.

Future responsibilities:

- run or consume coverage.py data;
- map tests to covered files and lines;
- normalize coverage records before persistence.

Dependencies:

- `database`

### `pytest_alchemist.diff_picker`

Owns changed-code based candidate selection. In the current skeleton it returns
mocked changed lines and selects tests whose historical coverage overlaps those
lines.

Future responsibilities:

- inspect recent git commits or diffs;
- identify changed files and lines;
- query historical coverage data;
- return candidate tests and target changes for minimization.

Dependencies:

- `database`

### `pytest_alchemist.minimizer`

Owns test set minimization algorithms. This module is intentionally pure: it
receives candidates and supporting data as input and returns selected tests.

Current behavior:

- deterministic mock selection based on candidate duration and changed-file
  coverage.

Future responsibilities:

- provide baseline greedy minimization;
- provide MOPSO-based minimization;
- optimize for coverage, runtime, risk, and other objectives.

Dependencies:

- none

### `pytest_alchemist.database`

Owns persistence-facing APIs. In the current skeleton it is an in-memory facade
with deterministic mock data.

Future responsibilities:

- manage SQLite connections and schema;
- persist coverage records;
- persist test run history;
- expose small repository-style APIs to other modules.

Dependencies:

- none

## Dependency Graph

```text
cli
└── application
    ├── coverage_analysis
    │   └── database
    ├── diff_picker
    │   └── database
    ├── minimizer
    ├── test_runner
    └── database
```

Rules:

- `cli` should only depend on `application`.
- `application` coordinates modules but should not contain algorithmic logic.
- `test_runner` should not depend on `database`; it returns run results to the
  application layer.
- `minimizer` should not depend on `database`, `coverage_analysis`, or
  `diff_picker`.
- `database` should expose persistence through a facade or repositories instead
  of leaking SQLite details into other modules.

## Main Scenario Flow

```text
pytest-alchemist run-minimal --last-commits N
  -> cli
  -> application.run_minimal(N)
  -> diff_picker.pick_candidates(N)
  -> minimizer.minimize(...)
  -> test_runner.run_tests(...)
  -> database.save_test_run(...)
```

The same boundaries should be preserved when mocked components are replaced
with real implementations.

## Project Artifacts

All project-specific data produced by `pytest-alchemist` should be stored under
the target project root in:

```text
.pytest-alchemist-artifacts/
```

This directory is owned by `pytest-alchemist` for the current target project.
It stores test run artifacts such as stdout, stderr, and coverage reports.
Future SQLite databases and other project-level artifacts should also live
under this directory.
