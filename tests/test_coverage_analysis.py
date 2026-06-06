import sqlite3
import sys
from pathlib import Path

import coverage

from pytest_alchemist.coverage_analysis.analyzer import (
    CoverageAnalyzer,
    build_file_entity_index,
    parse_pytest_context,
)
from pytest_alchemist.database.facade import DatabaseFacade
from pytest_alchemist.test_runner.runner import TestRunner


def test_parse_pytest_context_accepts_known_phases() -> None:
    assert parse_pytest_context("tests/test_calc.py::test_add|setup") == (
        "tests/test_calc.py::test_add",
        "setup",
    )
    assert parse_pytest_context("tests/test_calc.py::test_add|run") == (
        "tests/test_calc.py::test_add",
        "run",
    )
    assert parse_pytest_context("tests/test_calc.py::test_add|teardown") == (
        "tests/test_calc.py::test_add",
        "teardown",
    )


def test_parse_pytest_context_preserves_parametrized_nodeid() -> None:
    assert parse_pytest_context("tests/test_calc.py::test_add[case-a]|run") == (
        "tests/test_calc.py::test_add[case-a]",
        "run",
    )


def test_parse_pytest_context_uses_unknown_phase() -> None:
    assert parse_pytest_context("tests/test_calc.py::test_add|collect") == (
        "tests/test_calc.py::test_add",
        "unknown",
    )


def test_parse_pytest_context_rejects_empty_and_non_pytest_contexts() -> None:
    assert parse_pytest_context("") is None
    assert parse_pytest_context("import-time") is None


def test_build_file_entity_index_maps_lines_to_smallest_symbol(tmp_path: Path) -> None:
    source_path = tmp_path / "src" / "app" / "users.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "\n".join(
            [
                "VALUE = 1",
                "",
                "def outer():",
                "    def inner():",
                "        return VALUE",
                "    return inner()",
                "",
                "class UserService:",
                "    def create_user(self):",
                "        return outer()",
                "",
            ]
        ),
        encoding="utf-8",
    )

    index = build_file_entity_index(tmp_path, source_path)

    assert index.entity_for_line(1).kind == "module"
    assert index.entity_for_line(3).qualified_name == "app.users.outer"
    assert index.entity_for_line(5).qualified_name == "app.users.outer.inner"
    assert index.entity_for_line(9).kind == "method"
    assert index.entity_for_line(9).qualified_name == (
        "app.users.UserService.create_user"
    )
    assert index.entity_for_line(10).start_line == 9


def test_coverage_analyzer_persists_context_entities_lines_and_arcs(
    tmp_path: Path,
) -> None:
    (tmp_path / "calc.py").write_text(
        "\n".join(
            [
                "def classify(value):",
                "    if value > 0:",
                "        return 'positive'",
                "    return 'other'",
                "",
            ]
        ),
        encoding="utf-8",
    )
    tests_path = tmp_path / "tests"
    tests_path.mkdir()
    (tests_path / "test_calc.py").write_text(
        "\n".join(
            [
                "from calc import classify",
                "",
                "def test_positive():",
                "    assert classify(1) == 'positive'",
                "",
            ]
        ),
        encoding="utf-8",
    )
    database = DatabaseFacade(tmp_path)

    test_report_path = TestRunner().run_tests(str(tmp_path), collect_coverage="sqlite")
    database.save_test_run(test_report_path)
    result = CoverageAnalyzer(database).collect_from_report(test_report_path)

    assert result.quality == "complete"
    assert result.entity_count > 0
    assert result.line_fact_count > 0
    assert result.arc_fact_count > 0
    assert "calc.py" in result.covered_files
    assert database.list_coverage_tests() == [
        "tests/test_calc.py::test_positive"
    ]

    entities = database.list_entities_covered_by_test(
        "tests/test_calc.py::test_positive",
    )
    assert any(entity.qualified_name == "calc.classify" for entity in entities)
    assert database.list_arcs_covered_by_test(
        "tests/test_calc.py::test_positive",
    )

    with sqlite3.connect(database.database_path) as connection:
        connection.row_factory = sqlite3.Row
        artifact = connection.execute(
            """
            SELECT quality, has_contexts, has_arcs
            FROM coverage_artifacts
            WHERE run_uid = ? AND format = 'sqlite'
            """,
            (result.run_uid,),
        ).fetchone()

    assert artifact["quality"] == "complete"
    assert artifact["has_contexts"] == 1
    assert artifact["has_arcs"] == 1


def test_coverage_analyzer_prefers_parallel_artifact_with_contexts_and_arcs(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "calc.py"
    source_path.write_text(
        "\n".join(
            [
                "def classify(value):",
                "    if value > 0:",
                "        return 'positive'",
                "    return 'other'",
                "",
            ]
        ),
        encoding="utf-8",
    )
    tests_path = tmp_path / "tests"
    tests_path.mkdir()
    (tests_path / "test_calc.py").write_text(
        "\n".join(
            [
                "from calc import classify",
                "",
                "def test_positive():",
                "    assert classify(1) == 'positive'",
                "",
            ]
        ),
        encoding="utf-8",
    )
    database = DatabaseFacade(tmp_path)
    test_report_path = TestRunner().run_tests(str(tmp_path), collect_coverage="sqlite")
    report_dir = Path(test_report_path).parent
    base_coverage_path = report_dir / ".coverage"
    parallel_coverage_path = report_dir / ".coverage.worker"
    base_coverage_path.replace(parallel_coverage_path)
    _write_statement_only_coverage(base_coverage_path, source_path)

    database.save_test_run(test_report_path)
    result = CoverageAnalyzer(database).collect_from_report(test_report_path)

    assert result.quality == "complete"
    assert result.line_fact_count > 0
    assert result.arc_fact_count > 0
    assert any("parallel coverage artifact" in warning for warning in result.warnings)

    with sqlite3.connect(database.database_path) as connection:
        connection.row_factory = sqlite3.Row
        artifact = connection.execute(
            """
            SELECT path, quality, has_contexts, has_arcs
            FROM coverage_artifacts
            WHERE run_uid = ? AND format = 'sqlite' AND quality IS NOT NULL
            """,
            (result.run_uid,),
        ).fetchone()

    assert artifact["path"] == str(parallel_coverage_path)
    assert artifact["quality"] == "complete"
    assert artifact["has_contexts"] == 1
    assert artifact["has_arcs"] == 1


def _write_statement_only_coverage(coverage_path: Path, source_path: Path) -> None:
    old_path = list(sys.path)
    sys.path.insert(0, str(source_path.parent))
    try:
        cov = coverage.Coverage(data_file=str(coverage_path), branch=False)
        namespace: dict[str, object] = {}
        cov.start()
        try:
            code = compile(
                source_path.read_text(encoding="utf-8"),
                str(source_path),
                "exec",
            )
            exec(code, namespace)
            namespace["classify"](1)  # type: ignore[index,operator]
        finally:
            cov.stop()
        cov.save()
    finally:
        sys.path[:] = old_path
