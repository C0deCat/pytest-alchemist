# DiffPicker Module

`diff_picker` is responsible only for identifying tests affected by committed
code changes.

It inspects either the latest `N` committed changes or one explicit commit,
extracts changed Python files and changed lines, connects those changes to stored
coverage facts, and returns the full set of tests that covered any affected code.

It must not rank tests, optimize the returned set, infer which tests are
"enough", or make risk-based decisions. If a test is connected to a change by
the available coverage data, it belongs in the result.

## Responsibility Boundary

`diff_picker` owns:

- inspecting recent git history for the last `N` commits or one explicit commit;
- extracting changed project files and changed line ranges from diffs;
- normalizing those changes into a stable internal representation;
- querying coverage facts for tests that touched the changed code;
- returning the complete calculated affected-test set together with the changes
  that produced it.

`diff_picker` does not own:

- collecting coverage data;
- storing coverage facts;
- minimizing candidate tests;
- ranking tests by importance, duration, or risk;
- deciding that one affected test can replace another;
- running pytest.

Those responsibilities belong to other modules:

```text
coverage_analysis -> stores factual test-to-code relationships
diff_picker      -> connects recent changes to those relationships
minimizer        -> optionally reduces the affected-test set later
test_runner      -> executes tests
```

## Input Data

The module consumes two categories of facts.

### Recent Git Changes

For the latest `N` commits, `diff_picker` needs factual diff information such as:

```text
commit ids
changed files
changed line numbers or ranges
change type: added, modified, deleted, renamed
```

The first MVP represents changes as project-relative file paths split by change
kind:

```python
ChangedCode(
    file_path="src/app/users.py",
    added_lines=[42],
    modified_lines=[43, 44],
    deleted_lines=[41],
)
```

### Coverage Facts

`diff_picker` queries coverage data produced by `coverage_analysis`.

Useful relationships include:

```text
test A covered file F line L
test A covered entity E
test A covered branch arc R
```

The minimum viable matching rule is line overlap:

```text
changed file + changed line
  intersects
covered file + covered line
  -> affected test
```

Later versions may use normalized entities and branch arcs from the coverage
model to survive code movement more reliably, but the output contract remains
the same: return all tests that are factually connected to the change.

For the MVP, `last_commits=N` means a single committed-history comparison:

```text
HEAD~N..HEAD
```

Working-tree changes and staged-but-uncommitted changes are outside the first
scope.

When a single commit hash is supplied, `diff_picker` inspects only that commit's
patch.

## Output Contract

`diff_picker` returns:

1. the changed code that was inspected;
2. the complete set of tests affected by those changes;
3. optionally, the supporting coverage facts used to establish that
   relationship;
4. diagnostic metadata that explains missing or degraded coverage and why an
   affected-test set may be empty.

Conceptually:

```python
TestSelection(
    candidates=[...],
    target_changes=[...],
    coverage_records=[...],
    evidence=[...],
    diagnostics=SelectionDiagnostics(...),
)
```

The name `candidates` means "candidate input for later modules", not "already
optimized" or "recommended subset".

The result must be deterministic for the same git state and the same coverage
state.

## Selection Rule

The core rule is intentionally simple:

```text
for each changed location:
  find every test that covered that location

return the union of all such tests
```

Examples:

```text
change: src/app/users.py line 42
coverage:
  test_create_user covered line 42
  test_delete_user covered line 42

result:
  test_create_user
  test_delete_user
```

```text
change: src/app/users.py lines 42-44
coverage:
  test_create_user covered line 42
  test_delete_user covered line 90

result:
  test_create_user
```

No further reduction happens inside `diff_picker`.

## Intended Flow

```text
application.select_tests(last_commits=N | commit_hash=HASH)
  -> diff_picker.pick_candidates(...)
  -> inspect git history
  -> build changed-code model
  -> query coverage facts
  -> union all matching tests
  -> return TestSelection
```

For `run-minimal`, the same output becomes the input to a later minimization
step:

```text
diff_picker result
  -> minimizer
  -> selected minimal set
```

The boundary matters: the minimizer is allowed to decide, while `diff_picker`
is only allowed to calculate.

## MVP Behavior

The first real implementation should support:

1. reading the committed history range `HEAD~N..HEAD`;
2. reading one explicit commit by hash;
3. collecting changed Python source files and changed line numbers;
4. handling ordinary additions and modifications through current-side line
   matching;
5. acknowledging deleted lines from the old side of the diff;
6. matching current-side changed file/line pairs against stored coverage line
   facts;
7. returning every matching test exactly once;
8. returning an empty affected-test set when no stored coverage overlaps the
   changed code;
9. returning diagnostics that explain whether the empty result means no overlap,
   missing coverage, degraded coverage, or current-only coverage limitations.

The MVP may postpone:

- rename tracking;
- fully matching deleted lines;
- branch-arc matching;
- entity-level matching;
- merge-commit edge cases;
- uncommitted working-tree changes;
- fallback strategies for missing coverage.

Those features can be added without changing the module's core responsibility.

## Edge Cases

### Added Lines

Added lines can be matched directly when later coverage already exists for the
new location. If no historical coverage exists yet, no affected test can be
derived purely from past facts.

### Modified Lines

Modified lines should be represented by their new-file locations for the MVP so
they can be compared to the current normalized coverage index.

### Deleted Lines

Deleted lines must be acknowledged because removing previously executed logic can
change behavior just as much as adding or modifying code.

For the MVP, deleted lines should be represented explicitly from the old side of
the diff. With current-only coverage, they cannot be matched reliably because the
coverage snapshot describes code that exists now, while deleted lines existed
only in the old revision. The result should expose that limitation through
diagnostics instead of silently pretending the deletion was irrelevant.

### Renamed or Moved Code

Rename detection can improve recall, but it should remain a factual mapping
problem, not a heuristic ranking problem. A later version may use git rename
detection plus normalized coverage entities to preserve continuity.

### Missing Coverage

If no coverage facts are available, `diff_picker` cannot truthfully identify
affected tests. It should expose that absence through diagnostics rather than
inventing tests or silently widening the selection.

Suggested empty-result reasons:

```text
no_changed_python_files
no_matching_coverage
coverage_missing
coverage_degraded
deleted_lines_present_but_unmatched_with_current_coverage
```

## Current-Only Coverage Contract

The first implementation uses only the latest available coverage snapshot for
the current source tree. That choice keeps selection cheap and preserves the
practical value of minimization.

With current-only coverage, `diff_picker` can truthfully:

- match added lines that exist in current code;
- match modified code by its new-side/current line locations;
- return every test that currently covers any matched changed line;
- report when deleted lines were present in the diff but could not be resolved
  from current coverage alone.

With current-only coverage, `diff_picker` cannot truthfully reconstruct:

- which tests covered deleted lines that no longer exist;
- which tests covered the old version of a rewritten line before the change;
- complete historical impact for prior revisions that are not represented by the
  current coverage snapshot.

That limitation is acceptable for the MVP as long as it is visible to the user.

## Non-Goals

`diff_picker` should not:

- choose the smallest sufficient test set;
- prefer fast tests over slow tests;
- estimate failure probability;
- expand the result to nearby tests "just in case";
- hide affected tests because another test appears to cover the same code;
- decide whether missing coverage should trigger a full test suite run.

Those are policy or optimization questions for other layers.

## Current Decisions

- Source scope: committed history only.
- Git range semantics: `last_commits=N` means `HEAD~N..HEAD`.
- Single-commit semantics: `commit_hash=HASH` inspects only that commit patch.
- File scope: Python source files only.
- Matching basis: raw file-and-line overlap first.
- Coverage scope: current coverage snapshot only.
- Added lines: match against current coverage when they exist in the current
  source tree.
- Modified lines: match by their current/new-side positions.
- Deleted lines: included from the old side of the diff and surfaced explicitly,
  but not fully matchable from current-only coverage.
- Missing or degraded coverage: returned as diagnostics and surfaced to the user.

## Open Questions

- Should rename detection be enabled in the first git integration, or treated as
  a later recall improvement?
