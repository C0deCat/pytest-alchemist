# Minimizer Module

`minimizer` owns the policy and algorithms that reduce an already prepared set
of affected tests into a smaller useful subset.

It receives factual input from earlier stages and returns a selected set. It must
not inspect git history, read the database, collect coverage, or run pytest.

```text
diff_picker      -> calculates affected candidates
minimizer        -> chooses a smaller useful subset
test_runner      -> executes the chosen tests
```

The intended long-term algorithm is a manually implemented Multi-Objective
Particle Swarm Optimization solver, or MOPSO, written with NumPy rather than an
optimization library. That keeps the behavior inspectable and lets the project
own every modeling decision.

## Current Input Contract

The current minimizer input contains:

```python
MinimizationInput(
    candidates=[TestCase(...), ...],
    target_changes=[ChangedCode(...), ...],
    coverage_records=[CoverageRecord(...), ...],
)
```

From those values the minimizer can already derive:

- which candidate tests exist;
- each candidate's estimated duration;
- which changed files and changed current-side lines are covered by which tests;
- how many tests are selected in a candidate subset.

That means the first real optimizer can work with:

- changed-line coverage;
- total estimated runtime;
- selected test count.

Other ideas such as historical failure probability, flakiness, recency, or test
priority are not available through the current input contract and should not be
silently invented inside the minimizer.

## What MOPSO Is

Classical Particle Swarm Optimization keeps a population of candidate solutions
called particles. Each particle has:

- a position: the current solution;
- a velocity: the direction and intensity of its next move;
- a personal best: the best solution that particle has seen;
- access to a swarm leader: a strong solution found by the wider population.

For a single objective, "best" is a total ordering: one solution has a lower
cost than another. For multiple objectives, that is usually impossible. A test
subset can be faster but cover less changed code, while another covers more code
but takes longer.

MOPSO replaces one global best with a set of non-dominated solutions called the
Pareto archive.

For this project, each particle is one concrete candidate test subset. If the
candidate pool is:

```text
T1, T2, T3, T4, T5
```

then a particle position such as:

```text
[1, 0, 1, 0, 1]
```

means:

```text
select T1, T3, and T5
skip T2 and T4
```

Every particle therefore represents one complete answer to the minimization
problem at a given iteration.

### Pareto Dominance

For minimization objectives, solution `A` dominates solution `B` when:

1. `A` is no worse than `B` in every objective; and
2. `A` is strictly better than `B` in at least one objective.

Example:

```text
A = 100% changed-line coverage, 4.0 seconds, 3 tests
B = 100% changed-line coverage, 6.5 seconds, 4 tests
```

`A` dominates `B`.

But:

```text
A = 100% changed-line coverage, 6.0 seconds, 3 tests
B = 90% changed-line coverage, 2.0 seconds, 1 test
```

Neither dominates the other unless the model declares full coverage to be a hard
requirement.

### Main MOPSO Loop

At a high level, each iteration does this:

1. Evaluate every particle as a candidate test subset.
2. Update each particle's personal best from the new result.
3. Merge newly found non-dominated solutions into the external archive.
4. Remove archive entries dominated by better solutions.
5. Choose archive leaders for the particles, usually favoring sparse regions of
   the Pareto front so the swarm does not collapse onto one trade-off.
6. Update velocities from inertia, personal-best attraction, and leader
   attraction.
7. Update particle positions.
8. Decode positions back into test subsets and continue until the stopping rule
   is met.

The velocity update in ordinary PSO is conceptually:

```text
new_velocity =
    inertia_component
    + cognitive_component_toward_personal_best
    + social_component_toward_archive_leader
```

The three coefficients answer three different questions:

- inertia: how much momentum should a particle keep;
- cognitive weight: how strongly should it trust its own experience;
- social weight: how strongly should it move toward good swarm discoveries.

## Why This Problem Is Discrete

The natural minimization decision is binary:

```text
dimension i = whether candidate test i is included in the subset
```

So a particle represents a subset of tests rather than a continuous point in
space.

There are two practical ways to adapt MOPSO:

### Option A: Binary MOPSO

- Store binary positions, one bit per candidate test.
- Keep real-valued velocities.
- Convert each velocity through a transfer function such as a sigmoid.
- Use the resulting probability to decide whether each bit should be `0` or `1`.

This is close to established binary PSO literature and maps neatly onto the
problem domain.

### Option B: Continuous Latent Positions With Thresholding

- Store positions as real numbers in `[0, 1]`.
- Interpret values above a threshold as selected tests.
- Let ordinary velocity updates move the latent values.

This is easier to reason about initially, but thresholding can make nearby
positions decode to the same subset and can flatten the search landscape.

### Recommended Starting Choice

Start with Binary MOPSO.

The problem is genuinely combinatorial, and the binary representation makes that
explicit. It also gives us a clean place to add repair rules and mutation without
pretending that a test subset is naturally continuous.

### Binary Position and Velocity

With `n_tests` candidates, every particle has:

```text
position: length n_tests
velocity: length n_tests
```

Example:

```text
position = [1, 0, 1, 0, 0]
velocity = [2.1, -0.8, 1.4, 0.2, -2.7]
```

The position is the concrete current subset. The velocity is not a partially
selected subset and it is not a geometric movement through continuous space. In
Binary MOPSO, velocity is a per-test tendency that controls how likely each bit
is to be `1` in the next iteration.

For the first implementation, use the sigmoid set-bit interpretation:

```text
probability_of_selecting_test_i = sigmoid(velocity_i)
```

Examples:

```text
velocity = -3.0 -> probability near 0.05
velocity =  0.0 -> probability 0.50
velocity =  3.0 -> probability near 0.95
```

After the velocity vector is updated, each next position bit is sampled from its
own probability. That means a particle's subset can add some tests, remove
others, and keep the rest during one iteration.

### How A Particle Changes During One Iteration

Suppose a particle currently has:

```text
current position = [1, 0, 1, 0, 0]
personal best    = [1, 1, 0, 0, 0]
archive leader   = [1, 1, 0, 1, 0]
```

For each test dimension:

```text
+1 pressure means move toward selecting the test
 0 pressure means no direct preference change
-1 pressure means move toward dropping the test
```

The ordinary PSO update still supplies the structure:

```text
new_velocity =
    inertia_component
    + cognitive_component_toward_personal_best
    + social_component_toward_archive_leader
```

Applied bit by bit, the cognitive and social components come from:

```text
personal_best_bit - current_bit
leader_bit - current_bit
```

So in the example:

- `T2` has current bit `0`, personal-best bit `1`, and leader bit `1`, so its
  velocity should be pushed upward and the test becomes more likely to be added;
- `T3` has current bit `1`, personal-best bit `0`, and leader bit `0`, so its
  velocity should be pushed downward and the test becomes more likely to be
  removed;
- `T4` agrees with the current position in the personal best but is selected by
  the leader, so it gets only social pressure toward inclusion.

After sigmoid conversion and random sampling, the next concrete subset might be:

```text
[1, 1, 0, 1, 0]
```

meaning the particle changed from selecting `{T1, T3}` to selecting
`{T1, T2, T4}`.

For the whole swarm, the natural NumPy shapes are:

```text
positions.shape  = (n_particles, n_tests)
velocities.shape = (n_particles, n_tests)
```

## Feasibility Before Optimization

This is the most important modeling decision.

If changed-line coverage is only one soft objective, the Pareto archive will
legitimately contain very small subsets that are fast precisely because they miss
important changed code. That is mathematically valid but not always useful for a
tool whose job is to choose tests worth running.

We should distinguish:

- **feasibility rules**: what a solution must satisfy to be acceptable;
- **optimization objectives**: how we compare acceptable solutions.

### Recommended Initial Policy

Treat coverable changed-line coverage as a hard feasibility rule:

```text
selected subset must cover every changed current-side line that is covered by
at least one candidate test
```

Then compare feasible subsets by:

1. total estimated duration as the primary optimization metric;
2. selected test count only as a deterministic tiebreaker when runtimes differ
   by no more than a configurable runtime tolerance measured in milliseconds.

Coverage should still be measured and reported, but the first useful MOPSO model
should not trade away known relevant changed-line coverage just to become faster.

### Why "Coverable" Matters

The current pipeline may contain:

- changed lines with no matching coverage at all;
- deleted lines that current-only coverage cannot match;
- degraded coverage inputs.

The minimizer cannot manufacture coverage that the upstream data does not
contain. Its feasibility rule should therefore apply to the universe of target
lines that are actually coverable by the candidate set, while diagnostics about
uncovered or unmatchable changes remain visible to the application layer.

## Candidate Objectives

The MVP has exactly three criteria:

1. changed-line coverage;
2. estimated runtime;
3. selected test count.

They do not have equal decision weight:

- changed-line coverage is the safety boundary;
- estimated runtime is the primary optimization metric among feasible subsets;
- selected test count is a deterministic tiebreaker for subsets whose runtime
  delta is within a configurable tolerance measured in milliseconds.

### 1. Changed-Line Coverage

Question answered:

```text
How much of the relevant changed code does this subset exercise?
```

Suggested first interpretation:

- use changed current-side lines, not whole files;
- count only lines present in `ChangedCode.current_lines`;
- intersect them with `CoverageRecord.lines`;
- define the feasible coverage universe as changed lines covered by at least one
  candidate test.

### 2. Estimated Runtime

Question answered:

```text
How long should this subset take to run?
```

Suggested first interpretation:

- sum `TestCase.estimated_duration` across selected tests;
- minimize the total.

Runtime is one of the strongest reasons to minimize at all, so it should be a
primary objective from the first implementation.

### 3. Selected Test Count

Question answered:

```text
How large is the selected subset?
```

This is not identical to runtime. Two fast unit tests may take less time than
one slow integration test, but count still matters for readability, debugging,
and execution overhead. For the MVP it should not beat a materially faster
subset; it only breaks ties between subsets whose runtime delta is within the
configured tolerance.

## Agreed First Objective Model

For the first real MOPSO implementation:

### Hard Rules

- select only from `input_data.candidates`;
- every coverable changed current-side line must be covered by at least one
  selected test;
- the empty subset is infeasible whenever at least one coverable target line
  exists.

Changed-line coverage is the MVP safety boundary. The evaluator should be kept
open for extension so later feasibility criteria such as file-level coverage or
entity-level coverage can be added without changing the MOPSO core. The first
implementation should therefore keep coverage evaluation in explicit evaluator
logic rather than burying changed-line assumptions directly inside swarm update
code.

### Optimization Objectives

For feasible subsets:

1. minimize total estimated runtime;
2. when two runtimes differ by no more than the configured runtime tolerance,
   choose the subset with the smaller selected test count.

### Optional Reporting Metrics

Report, but do not optimize yet:

- changed-line coverage percentage;
- number of target lines with no available candidate coverage;
- number of selected tests;
- estimated runtime;
- maybe archive size and chosen Pareto rank for observability.

This creates a clean MVP:

- correctness pressure comes from the feasibility rule;
- efficiency pressure comes primarily from runtime;
- subset size remains available as a deterministic tie-break;
- the optimizer stays focused on exactly the three agreed criteria.

### Runtime Tolerance

Estimated test duration is an approximation, not a promise of the next exact
execution time. In practice, two feasible selections that differ only by a small
number of milliseconds are not meaningfully different in runtime.

The minimizer should therefore use a configurable tolerance:

```text
runtime_delta_ms <= runtime_tolerance_ms
```

When that condition is true, selected test count becomes the deterministic
tiebreaker. The tolerance should remain a parameter rather than a hard-coded
constant so it can be chosen from field experience and tuned for different
projects.

## Suggested Internal Representation

Assume `n_tests` candidate tests and `n_targets` coverable changed lines.

The optimizer can precompute:

- `durations`: shape `(n_tests,)`;
- `coverage_matrix`: shape `(n_tests, n_targets)`, boolean;
- `positions`: shape `(n_particles, n_tests)`, binary;
- `velocities`: shape `(n_particles, n_tests)`, float;
- `objective_values`: shape `(n_particles, n_objectives)`;
- `personal_best_positions`: shape `(n_particles, n_tests)`;
- an external archive containing non-dominated feasible subsets.

This is a good fit for NumPy because:

- total runtime is a vectorized masked sum;
- selected test count is a vectorized bit count;
- coverage can be evaluated with matrix operations;
- dominance checks can be written explicitly and tested independently.

## Repair and Search Operators

Because particles may propose infeasible subsets, the implementation needs an
explicit policy.

### Repair

For a subset missing required target lines:

1. identify uncovered target lines;
2. add candidate tests that cover them;
3. prefer tests with the best marginal uncovered-line gain per estimated runtime;
4. stop when all coverable targets are covered or no progress is possible.

After coverage is satisfied, an optional prune pass can remove selected tests
whose removal preserves feasibility.

Repair is useful because it converts random exploratory particles into valid
solutions instead of wasting most evaluations on obviously unusable subsets.

### Mutation

Binary swarms can lose diversity early. A small mutation operator can:

- flip a few bits with low probability;
- target crowded archive regions less often than sparse ones;
- be stronger early and weaker late.

Mutation should be explicit and measurable, not hidden in unrelated logic.

## Archive Management

The external archive should contain non-dominated feasible subsets discovered so
far.

Recommended behavior:

- add new feasible non-dominated solutions;
- remove archive members dominated by newcomers;
- deduplicate identical bit vectors;
- cap archive size;
- when pruning is needed, preserve diversity using crowding distance or a simple
  grid-based density measure.

Leader selection should favor less crowded archive areas so that the swarm keeps
exploring different runtime/count trade-offs instead of collapsing onto one
region.

The archive is an internal optimizer structure only. It should not become part of
the public result contract.

## Choosing One Final Result

MOPSO naturally uses a Pareto archive internally, but the public API should
return one `selected_tests` list only.

We therefore need a final policy after the swarm finishes.

Choose the feasible archive solution with minimum runtime. If two or more
solutions differ by no more than the configured runtime tolerance, choose the
one with the smaller selected test count as a deterministic tiebreaker.

That matches the user-facing product promise most directly and fits the current
`MinimizationResult` contract. The Pareto archive remains hidden inside the
minimizer because it has no value to external callers in the MVP.

## Determinism and Reproducibility

The optimizer should accept an optional explicit random seed.

That gives us:

- reproducible experiments when a seed is provided;
- comparable runs across parameter changes;
- debuggable reports when one run behaves unexpectedly.

The public behavior should be:

- if `minimize(...)` receives a seed, use that seed;
- if `minimize(...)` receives no seed, generate one for that run.

The CLI should expose the optional seed parameter so ordinary runs get fresh
exploration by default, while experiments and reproductions can pass a known
seed explicitly.

## Proposed Implementation Shape

The first implementation should stay small and explicit:

```text
src/pytest_alchemist/minimizer/
  models.py              -> public input/output models shared by all strategies
  interface.py           -> common minimizer interface
  minimizer.py           -> public/default orchestration entry point
  evaluators.py          -> shared requirement evaluator contracts or helpers
  mopso/
    __init__.py
    optimizer.py          -> MOPSO orchestration
    archive.py            -> Pareto archive utilities
    repair.py             -> MOPSO repair strategies
    objectives.py         -> MOPSO objective evaluation
  greedy/
    __init__.py
    optimizer.py          -> future greedy implementation
```

Files that belong only to one minimization method should live inside that
method's folder. Files shared by all minimization methods should stay at the
same level as the implementation folders.

The split should be driven by real complexity. It is acceptable for a strategy
folder to start with fewer files if the first version stays readable.

### File Organization Guideline

The minimizer should be implemented as a set of small, comprehensible modules
with one clear purpose each instead of growing into one large algorithm file.

As a working guideline:

- prefer purpose-bound files;
- keep files for one strategy inside that strategy's folder;
- keep shared files at the minimizer package root beside the strategy folders;
- keep files around 300 lines of code or less when practical;
- split code when a file starts combining unrelated responsibilities or becomes
  difficult to understand in one pass.

The goal is not to satisfy an arbitrary line limit mechanically. The goal is to
keep the optimizer easy to inspect, test, tune, and extend.

### Public Interface Boundary

The outside-facing part of `minimizer` should expose a common minimizer
interface, while MOPSO remains one concrete implementation behind that boundary.

Callers such as `application` should depend on the shared contract:

```text
minimize(input_data, ...)
  -> MinimizationResult
```

and should not need to know whether the active implementation is MOPSO, greedy,
or another future minimization strategy.

The intended replacement cost should be low: changing the minimization approach
later should mainly mean changing which concrete minimizer class is constructed
in application wiring, not rewriting caller logic or changing the public result
shape.

## MVP Implementation Order

1. Define the exact target-line universe and the first coverage evaluator.
2. Build a boolean coverage matrix from candidates, changed lines, and coverage
   records.
3. Implement objective evaluation for runtime and selected count.
4. Implement Pareto dominance helpers and archive maintenance.
5. Implement binary particle state and velocity updates.
6. Add repair and optional prune behavior.
7. Add deterministic final-result selection.
8. Add tests for objective evaluation, dominance, archive behavior, repair, and
   end-to-end deterministic minimization.

## Parameters

The minimizer will use two different kinds of parameters:

- internal algorithm configuration that belongs to the implementation;
- external run parameters that callers may intentionally provide.

Keeping those categories separate matters. Most MOPSO controls are tuning knobs,
not product-level choices, and exposing all of them through the CLI would make
the user-facing interface noisy without making ordinary minimization better.

### Internal Algorithm Configuration

These values are part of the concrete implementation and should be recorded in a
single clearly visible code-level configuration area, for example near the top
of the MOPSO implementation module, so they are easy to inspect and adjust
manually:

- number of particles;
- number of iterations;
- inertia weight strategy;
- cognitive weight;
- social weight;
- velocity bounds;
- mutation probability;
- archive size limit;
- repair strategy;
- final result policy.

They define how the optimizer searches. The MVP should keep them inside the
minimizer implementation rather than expose them as CLI options.

The first implementation should also provide baseline values for these settings
immediately. They do not need to be final tuned values on day one, but they
should be reasonable starting values that let the algorithm run, be tested, and
be improved from evidence instead of leaving the configuration undecided.

### External Run Parameters

These are meaningful per-run choices and may come from callers such as the CLI:

- optional random seed;
- runtime tolerance in milliseconds.

The seed exists for experimentation and reproduction. If omitted, the minimizer
generates one for the run.

The runtime tolerance expresses product policy rather than swarm mechanics: it
defines how close two estimated runtimes must be before selected test count may
break the tie. It should stay configurable because the right threshold is best
chosen from real project behavior.

### CLI Exposure

For the MVP CLI:

- expose `--seed`;
- expose `--runtime-tolerance-ms`.
