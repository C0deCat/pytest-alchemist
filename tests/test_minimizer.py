import numpy as np

from pytest_alchemist.coverage_analysis.models import CoverageRecord
from pytest_alchemist.diff_picker.models import ChangedCode
from pytest_alchemist.minimizer import Minimizer
from pytest_alchemist.minimizer.evaluators import build_coverage_evaluation
from pytest_alchemist.minimizer.models import MinimizationInput
from pytest_alchemist.minimizer.greedy import GreedyOptimizer
from pytest_alchemist.minimizer.mopso.archive import ParetoArchive, dominates
from pytest_alchemist.minimizer.mopso.objectives import ObjectiveValue, prefers
from pytest_alchemist.minimizer.mopso.repair import (
    is_feasible,
    prune_position,
    repair_position,
)
from pytest_alchemist.test_runner.models import TestCase


def _input_data() -> MinimizationInput:
    candidates = [
        TestCase("tests/test_sample.py::test_a", "tests/test_sample.py", 0.04),
        TestCase("tests/test_sample.py::test_b", "tests/test_sample.py", 0.01),
        TestCase("tests/test_sample.py::test_c", "tests/test_sample.py", 0.02),
    ]
    return MinimizationInput(
        candidates=candidates,
        target_changes=[
            ChangedCode(
                file_path="src/sample.py",
                added_lines=[10],
                modified_lines=[11],
                deleted_lines=[12],
            )
        ],
        coverage_records=[
            CoverageRecord(candidates[0].nodeid, "src/sample.py", [10, 11]),
            CoverageRecord(candidates[1].nodeid, "src/sample.py", [10]),
            CoverageRecord(candidates[2].nodeid, "src/sample.py", [11]),
        ],
    )


def test_coverage_evaluation_uses_current_side_lines_and_candidate_coverage() -> None:
    candidate = TestCase("tests/test_sample.py::test_a", "tests/test_sample.py", 0.01)
    evaluation = build_coverage_evaluation(
        MinimizationInput(
            candidates=[candidate],
            target_changes=[
                ChangedCode(
                    file_path="src/sample.py",
                    added_lines=[10],
                    modified_lines=[11],
                    deleted_lines=[12],
                )
            ],
            coverage_records=[
                CoverageRecord(candidate.nodeid, "src/sample.py", [10]),
                CoverageRecord("tests/other.py::test_other", "src/sample.py", [11]),
            ],
        )
    )

    assert evaluation.all_target_lines == (("src/sample.py", 10), ("src/sample.py", 11))
    assert evaluation.coverable_target_lines == (("src/sample.py", 10),)
    assert evaluation.uncovered_target_count == 1
    assert evaluation.coverage_matrix.tolist() == [[True]]


def test_pareto_archive_rejects_dominated_entries_and_deduplicates_positions() -> None:
    archive = ParetoArchive(max_size=4)
    archive.add(np.array([True, False]), ObjectiveValue(runtime=0.3, selected_count=1))
    archive.add(np.array([True, False]), ObjectiveValue(runtime=0.3, selected_count=1))
    archive.add(np.array([True, True]), ObjectiveValue(runtime=0.5, selected_count=2))
    archive.add(np.array([False, True]), ObjectiveValue(runtime=0.2, selected_count=2))

    assert len(archive.entries) == 2
    assert dominates(
        ObjectiveValue(runtime=0.3, selected_count=1),
        ObjectiveValue(runtime=0.5, selected_count=2),
    )


def test_repair_adds_covering_tests_and_prune_removes_redundant_ones() -> None:
    coverage_matrix = np.array(
        [
            [True, True],
            [True, False],
            [False, True],
        ],
        dtype=bool,
    )
    durations = np.array([0.04, 0.01, 0.02], dtype=float)

    repaired = repair_position(
        np.array([False, False, False]),
        coverage_matrix,
        durations,
    )
    pruned = prune_position(
        np.array([True, True, True]),
        coverage_matrix,
        durations,
    )

    assert is_feasible(repaired, coverage_matrix)
    assert repaired.tolist() == [False, True, True]
    assert pruned.tolist() == [False, True, True]


def test_runtime_tolerance_uses_selected_count_only_for_near_ties() -> None:
    faster_more_tests = ObjectiveValue(runtime=1.0, selected_count=3)
    slightly_slower_fewer_tests = ObjectiveValue(runtime=1.005, selected_count=1)
    materially_slower_fewer_tests = ObjectiveValue(runtime=1.02, selected_count=1)
    slightly_faster_same_count = ObjectiveValue(runtime=0.995, selected_count=3)

    assert prefers(slightly_slower_fewer_tests, faster_more_tests, 10)
    assert not prefers(materially_slower_fewer_tests, faster_more_tests, 10)
    assert prefers(slightly_faster_same_count, faster_more_tests, 10)


def test_minimizer_is_deterministic_with_seed_and_reports_metrics() -> None:
    input_data = _input_data()
    minimizer = Minimizer()

    first = minimizer.minimize(input_data, seed=123)
    second = minimizer.minimize(input_data, seed=123)

    assert [test.nodeid for test in first.selected_tests] == [
        "tests/test_sample.py::test_b",
        "tests/test_sample.py::test_c",
    ]
    assert [test.nodeid for test in second.selected_tests] == [
        test.nodeid for test in first.selected_tests
    ]
    assert first.coverage_percent == 100.0
    assert first.uncovered_target_count == 0
    assert first.selected_test_count == 2
    assert first.estimated_runtime == 0.03
    assert first.seed == 123


def test_greedy_optimizer_selects_covering_subset_and_reports_metrics() -> None:
    input_data = _input_data()
    evaluation = build_coverage_evaluation(input_data)

    result = GreedyOptimizer().minimize(input_data, evaluation, seed=123)

    assert [test.nodeid for test in result.selected_tests] == [
        "tests/test_sample.py::test_a"
    ]
    assert result.coverage_percent == 100.0
    assert result.uncovered_target_count == 0
    assert result.selected_test_count == 1
    assert result.estimated_runtime == 0.04
    assert result.seed == 123


def test_greedy_optimizer_keeps_input_order_for_coverage_ties() -> None:
    candidates = [
        TestCase("tests/test_sample.py::test_b", "tests/test_sample.py", 0.03),
        TestCase("tests/test_sample.py::test_a", "tests/test_sample.py", 0.01),
    ]
    input_data = MinimizationInput(
        candidates=candidates,
        target_changes=[
            ChangedCode(
                file_path="src/sample.py",
                added_lines=[1],
                modified_lines=[],
                deleted_lines=[],
            )
        ],
        coverage_records=[
            CoverageRecord(candidates[0].nodeid, "src/sample.py", [1]),
            CoverageRecord(candidates[1].nodeid, "src/sample.py", [1]),
        ],
    )
    evaluation = build_coverage_evaluation(input_data)

    result = GreedyOptimizer().minimize(input_data, evaluation)

    assert [test.nodeid for test in result.selected_tests] == [
        "tests/test_sample.py::test_b"
    ]
    assert result.selected_test_count == 1
    assert result.estimated_runtime == 0.03


def test_greedy_optimizer_does_not_prune_redundant_selected_tests() -> None:
    candidates = [
        TestCase("tests/test_sample.py::test_a", "tests/test_sample.py", 0.01),
        TestCase("tests/test_sample.py::test_b", "tests/test_sample.py", 0.02),
        TestCase("tests/test_sample.py::test_c", "tests/test_sample.py", 0.03),
        TestCase("tests/test_sample.py::test_d", "tests/test_sample.py", 0.04),
    ]
    input_data = MinimizationInput(
        candidates=candidates,
        target_changes=[
            ChangedCode(
                file_path="src/sample.py",
                added_lines=[1, 2, 3, 4, 5, 6],
                modified_lines=[],
                deleted_lines=[],
            )
        ],
        coverage_records=[
            CoverageRecord(candidates[0].nodeid, "src/sample.py", [1, 2, 3]),
            CoverageRecord(candidates[1].nodeid, "src/sample.py", [1, 4]),
            CoverageRecord(candidates[2].nodeid, "src/sample.py", [2, 5]),
            CoverageRecord(candidates[3].nodeid, "src/sample.py", [3, 6]),
        ],
    )
    evaluation = build_coverage_evaluation(input_data)

    result = GreedyOptimizer().minimize(input_data, evaluation)

    assert [test.nodeid for test in result.selected_tests] == [
        "tests/test_sample.py::test_a",
        "tests/test_sample.py::test_b",
        "tests/test_sample.py::test_c",
        "tests/test_sample.py::test_d",
    ]
    assert result.selected_test_count == 4
    assert result.estimated_runtime == 0.1


def test_greedy_optimizer_is_deterministic() -> None:
    input_data = _input_data()
    evaluation = build_coverage_evaluation(input_data)

    first = GreedyOptimizer().minimize(input_data, evaluation)
    second = GreedyOptimizer().minimize(input_data, evaluation)

    assert [test.nodeid for test in second.selected_tests] == [
        test.nodeid for test in first.selected_tests
    ]


def test_minimizer_accepts_optimizer_names_and_instances() -> None:
    input_data = _input_data()
    captured: dict[str, object] = {}

    class _FakeOptimizer:
        def minimize(
            self,
            input_data: MinimizationInput,
            evaluation,
            seed: int | None = None,
            runtime_tolerance_ms: int = 10,
        ):
            captured["target_count"] = evaluation.target_count
            captured["seed"] = seed
            captured["runtime_tolerance_ms"] = runtime_tolerance_ms
            return Minimizer("greedy").minimize(
                input_data,
                seed=seed,
                runtime_tolerance_ms=runtime_tolerance_ms,
            )

    default_result = Minimizer().minimize(input_data, seed=123)
    mopso_result = Minimizer("mopso").minimize(input_data, seed=123)
    greedy_result = Minimizer("greedy").minimize(input_data, seed=123)
    fake_result = Minimizer(_FakeOptimizer()).minimize(
        input_data,
        seed=456,
        runtime_tolerance_ms=25,
    )

    assert [test.nodeid for test in default_result.selected_tests] == [
        test.nodeid for test in mopso_result.selected_tests
    ]
    assert [test.nodeid for test in greedy_result.selected_tests] == [
        "tests/test_sample.py::test_a"
    ]
    assert [test.nodeid for test in fake_result.selected_tests] == [
        test.nodeid for test in greedy_result.selected_tests
    ]
    assert captured == {
        "target_count": 2,
        "seed": 456,
        "runtime_tolerance_ms": 25,
    }


def test_minimizer_rejects_unknown_optimizer_name() -> None:
    try:
        Minimizer("unknown")  # type: ignore[arg-type]
    except ValueError as error:
        assert str(error) == "Unknown optimizer: unknown"
    else:
        raise AssertionError("Expected unknown optimizer name to fail.")


def test_minimizer_returns_empty_subset_when_no_coverable_lines_exist() -> None:
    candidate = TestCase("tests/test_sample.py::test_a", "tests/test_sample.py", 0.01)
    result = Minimizer().minimize(
        MinimizationInput(
            candidates=[candidate],
            target_changes=[
                ChangedCode(
                    file_path="src/sample.py",
                    added_lines=[10],
                    modified_lines=[],
                    deleted_lines=[],
                )
            ],
            coverage_records=[],
        ),
        seed=123,
    )

    assert result.selected_tests == []
    assert result.coverage_percent == 0.0
    assert result.uncovered_target_count == 1
    assert result.selected_test_count == 0
    assert result.estimated_runtime == 0.0


def test_greedy_optimizer_returns_empty_subset_when_no_coverable_lines_exist() -> None:
    candidate = TestCase("tests/test_sample.py::test_a", "tests/test_sample.py", 0.01)
    input_data = MinimizationInput(
        candidates=[candidate],
        target_changes=[
            ChangedCode(
                file_path="src/sample.py",
                added_lines=[10],
                modified_lines=[],
                deleted_lines=[],
            )
        ],
        coverage_records=[],
    )
    result = GreedyOptimizer().minimize(
        input_data,
        build_coverage_evaluation(input_data),
        seed=123,
    )

    assert result.selected_tests == []
    assert result.coverage_percent == 0.0
    assert result.uncovered_target_count == 1
    assert result.selected_test_count == 0
    assert result.estimated_runtime == 0.0
    assert result.seed == 123
