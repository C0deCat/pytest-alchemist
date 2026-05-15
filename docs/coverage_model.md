# Coverage Module

`coverage_analysis` is responsible only for collecting, normalizing, storing,
and maintaining coverage facts for a target project.

It must not shortlist tests, rank tests, minimize test sets, inspect git diffs
to decide relevance, or make risk decisions. Other models may consume coverage
facts to make those decisions, but the coverage model itself should remain a
source of evidence rather than a decision maker.

## MVP Approach

The MVP coverage model is based on Coverage.py's native `.coverage` SQLite data
file, collected with pytest-cov test contexts and branch coverage enabled.

Target-project configuration should only describe stable project-specific
coverage settings, especially which source packages or paths belong to the
project. Runtime pytest-cov flags are owned by `pytest-alchemist` and should be
added when it invokes pytest.

Recommended target-project configuration:

```toml
[tool.coverage.run]
relative_files = true
source_pkgs = ["target_package_name"]
```

The exact `source_pkgs` value belongs to the tested project. Projects may use
Coverage.py's `source` instead when package names are not the right shape.

When collecting MVP coverage, `pytest-alchemist` should invoke pytest with the
needed runtime options itself:

```text
--cov
--cov-context=test
--cov-branch
--cov-report=
--cov-config=<resolved coverage config path>
```

`--cov-config` should point to the configuration file selected for the target
project, such as `pyproject.toml`, `.coveragerc`, `tox.ini`, or `setup.cfg`.
`pytest-alchemist` should validate that the resulting `.coverage` file has
contexts and arcs before using the MVP coverage path.

## Responsibility Boundary

`coverage_analysis` owns:

- locating or receiving a `.coverage` artifact produced by a test run;
- reading Coverage.py execution data;
- verifying whether contexts and branch arcs are available;
- mapping raw files, lines, contexts, and arcs to stable project entities;
- storing raw artifacts and normalized coverage facts;
- maintaining historical coverage facts across commits when entities move;
- exposing query APIs for other modules.

`coverage_analysis` does not own:

- choosing which tests should be run;
- choosing which tests should be skipped;
- minimizing a candidate test set;
- deciding whether a changed file is risky;
- calculating final confidence scores for test selection;
- changing the user's source code or tests.

The coverage model may expose factual relationships such as:

```text
test A covered symbol B
test A executed branch arc C
test A last covered symbol B at commit D
symbol B was observed with normalized hash H
```

It should not expose decisions such as:

```text
test A should be selected
test A is enough for this change
test B is irrelevant
```

## Input Artifacts

The MVP consumes two artifacts from the same pytest run.

### `.coverage`

The primary source of coverage facts.

Expected content:

- measured files;
- dynamic contexts from `--cov-context=test`;
- executed lines per context;
- executed arcs per context from branch coverage;
- Coverage.py metadata such as version and whether arcs are present.

The implementation should prefer Coverage.py's public `CoverageData` API where
possible. Direct SQLite access can be used for diagnostics or unsupported API
gaps, but the schema should not become the domain contract.

### `test_report.json`

The source of test-run facts already produced by `test_runner`.

Useful fields:

- run uid;
- project root;
- selected node ids;
- pytest args;
- per-test results from `runned_tests`;
- test durations;
- coverage artifact paths.

The coverage model uses this report to connect the `.coverage` artifact to a
known run and to reconcile pytest node ids. It must not use the report to decide
which tests are important.

## Normalization Pipeline

The MVP pipeline should be:

```text
test_report.json
  -> locate run uid, project root, and .coverage artifact
  -> read Coverage.py files, contexts, lines, and arcs
  -> parse measured Python files with libCST
  -> map raw lines and arcs to modules, classes, functions, methods, and blocks
  -> normalize pytest-cov contexts into test node id and phase
  -> store raw artifact reference
  -> store normalized coverage facts
```

The normalized model should keep raw data for traceability, but raw line numbers
must not be the main long-term identity.

## Context Model

With pytest-cov, contexts are expected to look like:

```text
tests/test_users.py::test_create_user|setup
tests/test_users.py::test_create_user|run
tests/test_users.py::test_create_user|teardown
tests/test_users.py::test_parametrized[case-a]|run
```

The coverage model should split each context into:

```text
nodeid = "tests/test_users.py::test_create_user"
phase = "run"
```

Valid phases:

- `setup`
- `run`
- `teardown`
- `unknown`

Unknown phase is a defensive fallback for non-pytest-cov contexts or future
format changes.

The model should preserve parametrized node ids exactly as pytest reports them.
Parametrized cases are separate test identities.

## Code Entity Model

Raw file lines should be mapped into durable entities using `libCST`.

Recommended entity kinds:

- `module`
- `class`
- `function`
- `method`
- `statement_block`
- `branch_arc`

For each entity, store multiple anchors:

```text
project-relative file path
importable module name when known
qualified name when known
entity kind
start line at collection time
end line at collection time
normalized CST hash
parent entity
```

Examples:

```text
src/app/users.py
app.users
app.users.UserService.create_user
method
42
79
hash:...
parent: app.users.UserService
```

For module-level executed code, the parent entity can be the module itself.

## Line Coverage Facts

Line coverage should be stored as a relationship between a test context and a
normalized code entity.

Conceptually:

```text
run uid
test nodeid
phase
file
entity id
raw line
line offset within entity
```

The raw line is useful for debugging the original run. The line offset within a
stable entity is more useful for surviving code movement.

If a line cannot be mapped to a function, method, class, or block, map it to the
module entity.

## Branch Arc Facts

Branch coverage should be stored as first-class evidence.

Coverage.py arcs are raw transitions:

```text
from line -> to line
```

The coverage model should store both:

```text
raw arc: file.py:42 -> file.py:45
normalized arc: entity E, from block A -> to block B
```

The normalized arc is the survivable representation. The raw arc is the audit
trail.

Arcs are especially valuable because they distinguish behavior paths inside the
same symbol:

```text
validation success path
validation failure path
early return path
exception path
loop entered
loop skipped
```

The MVP does not need to assign semantic labels such as `success path`. It only
needs to preserve branch identity in a way other models can interpret later.

## Storage Shape

The exact database schema can evolve, but the model should separate raw
artifacts from normalized facts.

### Raw Artifact Record

The existing `coverage_artifacts` idea should include native Coverage.py data:

```text
run_uid
format = "sqlite"
path = ".pytest-alchemist-artifacts/test-runs/<run-uid>/.coverage"
sha256
coverage_py_version
has_contexts
has_arcs
created_at
```

### Normalized Entities

Suggested conceptual table:

```sql
CREATE TABLE coverage_entities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_uid TEXT NOT NULL,
  file_path TEXT NOT NULL,
  module_name TEXT,
  qualified_name TEXT,
  kind TEXT NOT NULL,
  start_line INTEGER,
  end_line INTEGER,
  normalized_hash TEXT,
  parent_id INTEGER
);
```

### Test-to-Line Facts

Suggested conceptual table:

```sql
CREATE TABLE coverage_line_facts (
  run_uid TEXT NOT NULL,
  nodeid TEXT NOT NULL,
  phase TEXT NOT NULL,
  entity_id INTEGER NOT NULL,
  raw_line INTEGER NOT NULL,
  entity_line_offset INTEGER,
  PRIMARY KEY (run_uid, nodeid, phase, entity_id, raw_line)
);
```

### Test-to-Arc Facts

Suggested conceptual table:

```sql
CREATE TABLE coverage_arc_facts (
  run_uid TEXT NOT NULL,
  nodeid TEXT NOT NULL,
  phase TEXT NOT NULL,
  entity_id INTEGER NOT NULL,
  from_line INTEGER NOT NULL,
  to_line INTEGER NOT NULL,
  from_offset INTEGER,
  to_offset INTEGER,
  arc_hash TEXT,
  PRIMARY KEY (
    run_uid,
    nodeid,
    phase,
    entity_id,
    from_line,
    to_line
  )
);
```

These tables describe collection facts only. They do not contain selection
scores, risk scores, or minimizer decisions.

## Survivability Strategy

Coverage facts should survive ordinary source movement.

Fragile identity:

```text
src/app/users.py:57
```

More durable identity:

```text
module: app.users
symbol: app.users.UserService.create_user
entity hash: hash of normalized CST body
line offset inside symbol: 8
arc hash inside symbol: normalized from/to block identity
```

When a new commit is analyzed, the coverage model can maintain old facts by
trying anchors in this order:

1. same project-relative file path and qualified name;
2. same qualified name with changed line range;
3. same normalized CST hash in a moved file;
4. same parent entity and similar normalized body hash;
5. raw line fallback only for diagnostics.

This maintenance step should update entity continuity metadata, not select
tests. It answers: "does this old coverage entity correspond to a current code
entity?"

## Validation Rules

The MVP context-aware model should mark a coverage artifact as degraded if:

- the `.coverage` file is missing;
- Coverage.py data cannot be read;
- no contexts are present;
- contexts do not contain pytest node ids;
- branch arcs are not present;
- measured files cannot be related to the project root;
- source files changed between the test run and normalization.

Degraded artifacts may still be stored, but consumers should be able to see why
they are incomplete.

Suggested artifact quality states:

```text
complete
missing_contexts
missing_arcs
unreadable
source_mismatch
partial
```

## Public Query Contract

The coverage model should expose factual query operations such as:

- get coverage artifact metadata for a run;
- list tests observed in coverage contexts for a run;
- list entities covered by a test in a run;
- list tests that covered an entity in a run;
- list arcs covered by a test in a run;
- list historical observations for an entity;
- report artifact quality and missing capabilities.

It should not expose:

- `select_tests_for_change`;
- `rank_tests`;
- `minimize`;
- `is_test_relevant`;
- `should_run`.

Those names belong to diff, impact, ranking, or minimization modules.

## MVP Deliverables

The first implementation should deliver:

1. native `.coverage` artifact registration;
2. Coverage.py data reader;
3. context parser for pytest-cov context strings;
4. branch arc extraction;
5. libCST file-to-entity mapper;
6. normalized line and arc fact persistence;
7. quality metadata for missing contexts or arcs;
8. read-only factual query API.

The MVP should explicitly reject or degrade non-context coverage rather than
silently pretending it has per-test attribution.

## Open Questions

- Should `test_runner.collect_coverage` grow a native `sqlite` mode, or should
  it always preserve `.coverage` when any coverage mode is enabled?
- Should setup and teardown coverage be exposed separately by default, or should
  consumers opt into phases?
- How much module import-time coverage should be attributed to an individual
  test when it appears in `setup` rather than `run`?
- Should old normalized entities be deduplicated across runs, or should every
  run store its own snapshot first and add continuity links later?
- Should coverage normalization happen immediately after a test run, or as a
  separate indexing command?
