"""Pytest execution infrastructure."""

from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pytest_alchemist.subprocess_utils import run_captured_text
from pytest_alchemist.test_runner import logger
from pytest_alchemist.test_runner.models import TestCase

CoverageFormat = Literal["json", "xml", "sqlite"]
TestInput = TestCase | str

ARTIFACTS_DIR_NAME = ".pytest-alchemist-artifacts"
REPORT_FILE_NAME = "test_report.json"


class TestRunner:
    """Run pytest in a target project and persist a JSON test report."""

    def run_tests(
        self,
        project_path: str,
        tests: list[TestInput] | None = None,
        collect_coverage: CoverageFormat | None = None,
        collects_tests: bool = True,
    ) -> str:
        """Run pytest and return a path to the generated test report."""

        if collect_coverage not in (None, "json", "xml", "sqlite"):
            raise ValueError(
                "collect_coverage must be 'json', 'xml', 'sqlite', or None."
            )

        resolved_project_path = Path(project_path).resolve()
        if not resolved_project_path.exists():
            raise FileNotFoundError(f"Project path does not exist: {resolved_project_path}")
        if not resolved_project_path.is_dir():
            raise NotADirectoryError(
                f"Project path is not a directory: {resolved_project_path}"
            )

        selected_tests = None if tests is None else list(tests)
        if selected_tests is not None and not selected_tests:
            return _write_empty_selection_report(
                resolved_project_path,
                collect_coverage,
                collects_tests,
            )

        nodeids = (
            []
            if selected_tests is None
            else [_to_nodeid(test) for test in selected_tests]
        )
        run_uid = _build_run_uid()
        run_dir = _create_run_dir(resolved_project_path, run_uid)
        stdout_path = run_dir / "stdout.txt"
        stderr_path = run_dir / "stderr.txt"
        test_report_path = run_dir / REPORT_FILE_NAME
        raw_reports_path = run_dir / "pytest_reports.jsonl"
        coverage = _build_coverage_data(run_dir, collect_coverage)

        command = [sys.executable, "-m", "pytest"]
        env = os.environ.copy()
        if collects_tests:
            command.extend(["-p", logger.PLUGIN_MODULE_NAME])
            env[logger.REPORTS_PATH_ENV] = str(raw_reports_path)
            env["PYTHONPATH"] = _prepend_pythonpath(
                _package_import_root(),
                env.get("PYTHONPATH"),
            )

        if coverage is not None:
            env["COVERAGE_FILE"] = str(coverage["coverage_sqlite_path"])
            coverage_config_path = _find_coverage_config(resolved_project_path)
            cov_arg = "--cov" if coverage_config_path is not None else "--cov=."
            command.extend([cov_arg, "--cov-context=test", "--cov-branch", "--cov-report="])
            if coverage_config_path is not None:
                command.append(f"--cov-config={coverage_config_path}")
            if collect_coverage == "json":
                command.append(f"--cov-report=json:{coverage['coverage_json_path']}")
            elif collect_coverage == "xml":
                command.append(f"--cov-report=xml:{coverage['coverage_xml_path']}")
        command.extend(nodeids)

        started_at = datetime.now(timezone.utc)
        started_monotonic = time.monotonic()
        completed = run_captured_text(
            command,
            cwd=resolved_project_path,
            env=env,
            check=False,
        )
        finished_at = datetime.now(timezone.utc)
        duration_seconds = round(time.monotonic() - started_monotonic, 3)

        stdout_path.write_text(completed.stdout, encoding="utf-8")
        stderr_path.write_text(completed.stderr, encoding="utf-8")

        runned_tests = (
            _normalize_reports(_read_raw_reports(raw_reports_path))
            if collects_tests
            else {}
        )
        summary = (
            _build_summary_from_runned_tests(runned_tests)
            if runned_tests
            else _parse_pytest_counts(f"{completed.stdout}\n{completed.stderr}")
        )

        report: dict[str, Any] = {
            "schema_version": 1,
            "uid": run_uid,
            "project_root": str(resolved_project_path),
            "started_at": _format_timestamp(started_at),
            "finished_at": _format_timestamp(finished_at),
            "duration_seconds": duration_seconds,
            "exit_code": completed.returncode,
            "status": "passed" if completed.returncode == 0 else "failed",
            "pytest": {
                "args": command,
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
            },
            "selection": {
                "selected_tests": nodeids,
            },
            "summary": summary,
            "runned_tests": runned_tests,
            "coverage": coverage,
            "artifacts": {
                "run_dir": str(run_dir),
                "test_report_path": str(test_report_path),
            },
        }
        test_report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        return str(test_report_path)


def _to_nodeid(test: TestInput) -> str:
    if isinstance(test, TestCase):
        return test.nodeid

    return test


def _build_run_uid() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def _create_run_dir(project_path: Path, run_uid: str) -> Path:
    run_dir = project_path / ARTIFACTS_DIR_NAME / "test-runs" / run_uid
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _write_empty_selection_report(
    project_path: Path,
    collect_coverage: CoverageFormat | None,
    collects_tests: bool,
) -> str:
    run_uid = _build_run_uid()
    run_dir = _create_run_dir(project_path, run_uid)
    stdout_path = run_dir / "stdout.txt"
    stderr_path = run_dir / "stderr.txt"
    test_report_path = run_dir / REPORT_FILE_NAME
    command = [sys.executable, "-m", "pytest"]
    started_at = datetime.now(timezone.utc)
    finished_at = datetime.now(timezone.utc)

    stdout_path.write_text("No tests selected.\n", encoding="utf-8")
    stderr_path.write_text("", encoding="utf-8")

    report: dict[str, Any] = {
        "schema_version": 1,
        "uid": run_uid,
        "project_root": str(project_path),
        "started_at": _format_timestamp(started_at),
        "finished_at": _format_timestamp(finished_at),
        "duration_seconds": 0.0,
        "exit_code": 0,
        "status": "passed",
        "pytest": {
            "args": command,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        },
        "selection": {
            "selected_tests": [],
        },
        "summary": {
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "total": 0,
        },
        "runned_tests": {},
        "coverage": None,
        "artifacts": {
            "run_dir": str(run_dir),
            "test_report_path": str(test_report_path),
        },
    }
    if collect_coverage is not None:
        report["coverage_warning"] = (
            "coverage was not collected because no tests were selected"
        )
    if collects_tests:
        report["collection_warning"] = "pytest was not started because no tests were selected"

    test_report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return str(test_report_path)


def _format_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _build_coverage_data(
    run_dir: Path,
    collect_coverage: CoverageFormat | None,
) -> dict[str, str | None] | None:
    if collect_coverage is None:
        return None

    coverage_json_path = str(run_dir / "coverage.json") if collect_coverage == "json" else None
    coverage_xml_path = str(run_dir / "coverage.xml") if collect_coverage == "xml" else None
    coverage_sqlite_path = str(run_dir / ".coverage")
    return {
        "format": collect_coverage,
        "coverage_json_path": coverage_json_path,
        "coverage_xml_path": coverage_xml_path,
        "coverage_sqlite_path": coverage_sqlite_path,
    }


def _find_coverage_config(project_path: Path) -> Path | None:
    pyproject = project_path / "pyproject.toml"
    if _file_contains(pyproject, "[tool.coverage"):
        return pyproject

    coveragerc = project_path / ".coveragerc"
    if coveragerc.exists():
        return coveragerc

    for filename in ("tox.ini", "setup.cfg"):
        candidate = project_path / filename
        if _file_contains(candidate, "[coverage:"):
            return candidate
    return None


def _file_contains(path: Path, value: str) -> bool:
    if not path.exists():
        return False
    return value in path.read_text(encoding="utf-8")


def _prepend_pythonpath(path: Path, existing: str | None) -> str:
    if existing:
        return f"{path}{os.pathsep}{existing}"
    return str(path)


def _package_import_root() -> Path:
    return Path(__file__).resolve().parents[2]



def _read_raw_reports(raw_reports_path: Path) -> list[dict[str, Any]]:
    if not raw_reports_path.exists():
        return []

    reports: list[dict[str, Any]] = []
    for line in raw_reports_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        reports.append(json.loads(line))
    return reports


def _normalize_reports(raw_reports: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for report in raw_reports:
        nodeid = str(report["nodeid"])
        grouped.setdefault(nodeid, []).append(report)

    runned_tests: dict[str, dict[str, Any]] = {}
    for nodeid, reports in grouped.items():
        outcomes = [str(report["outcome"]) for report in reports]
        call_report = next(
            (
                report
                for report in reports
                if report.get("when") == "call" and report.get("outcome") == "passed"
            ),
            None,
        )
        if "failed" in outcomes:
            outcome = "failed"
        elif "skipped" in outcomes:
            outcome = "skipped"
        elif call_report is not None:
            outcome = "passed"
        else:
            outcome = outcomes[-1] if outcomes else "failed"

        duration_ms = int(
            round(sum(float(report.get("duration", 0)) for report in reports) * 1000)
        )
        runned_tests[nodeid] = {
            "nodeid": nodeid,
            "outcome": outcome,
            "duration_ms": duration_ms,
        }

    return runned_tests


def _build_summary_from_runned_tests(
    runned_tests: dict[str, dict[str, Any]],
) -> dict[str, int]:
    passed = _count_outcome(runned_tests, "passed")
    failed = _count_outcome(runned_tests, "failed")
    skipped = _count_outcome(runned_tests, "skipped")
    return {
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "total": len(runned_tests),
    }


def _count_outcome(runned_tests: dict[str, dict[str, Any]], outcome: str) -> int:
    return sum(1 for test in runned_tests.values() if test["outcome"] == outcome)


def _parse_pytest_counts(output: str) -> dict[str, int]:
    passed = _sum_count(output, "passed")
    failed = _sum_count(output, "failed")
    skipped = _sum_count(output, "skipped")
    return {
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "total": passed + failed + skipped,
    }


def _sum_count(output: str, status: str) -> int:
    matches = re.findall(rf"(?<!\w)(\d+)\s+{re.escape(status)}(?!\w)", output)
    return sum(int(match) for match in matches)
