"""Pytest execution infrastructure."""

from __future__ import annotations

import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pytest_alchemist.test_runner.models import (
    CoverageRunArtifact,
    TestCase,
    TestRunResult,
)

CoverageFormat = Literal["json", "xml"]
TestInput = TestCase | str

ARTIFACTS_DIR_NAME = ".pytest-alchemist-artifacts"


def run_tests(
    project_path: str,
    tests: list[TestInput] | None = None,
    collect_coverage: CoverageFormat | None = None,
) -> TestRunResult:
    """Run pytest in a target project and return a structured result."""

    if collect_coverage not in (None, "json", "xml"):
        raise ValueError("collect_coverage must be 'json', 'xml', or None.")

    resolved_project_path = Path(project_path).resolve()
    if not resolved_project_path.exists():
        raise FileNotFoundError(f"Project path does not exist: {resolved_project_path}")
    if not resolved_project_path.is_dir():
        raise NotADirectoryError(f"Project path is not a directory: {resolved_project_path}")

    selected_tests = list(tests or [])
    nodeids = [_to_nodeid(test) for test in selected_tests]
    run_dir = _create_run_dir(resolved_project_path)
    stdout_path = run_dir / "stdout.txt"
    stderr_path = run_dir / "stderr.txt"
    coverage = _build_coverage_artifact(run_dir, collect_coverage)

    command = [sys.executable, "-m", "pytest", *nodeids]
    if collect_coverage == "json" and coverage is not None:
        command.extend(
            [
                "--cov",
                "--cov-context=test",
                f"--cov-report=json:{coverage.coverage_json_path}",
            ]
        )
    elif collect_coverage == "xml" and coverage is not None:
        command.extend(
            [
                "--cov",
                "--cov-context=test",
                f"--cov-report=xml:{coverage.coverage_xml_path}",
            ]
        )

    started_at = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=resolved_project_path,
        capture_output=True,
        text=True,
        check=False,
    )
    duration_seconds = round(time.monotonic() - started_at, 3)

    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")

    passed, failed = _parse_pytest_counts(f"{completed.stdout}\n{completed.stderr}")

    return TestRunResult(
        selected_tests=selected_tests,
        passed=passed,
        failed=failed,
        duration_seconds=duration_seconds,
        exit_code=completed.returncode,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        coverage=coverage,
    )


def _to_nodeid(test: TestInput) -> str:
    if isinstance(test, TestCase):
        return test.nodeid

    return test


def _create_run_dir(project_path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = (
        project_path
        / ARTIFACTS_DIR_NAME
        / "test-runs"
        / f"{timestamp}-{uuid.uuid4().hex[:8]}"
    )
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _build_coverage_artifact(
    run_dir: Path,
    collect_coverage: CoverageFormat | None,
) -> CoverageRunArtifact | None:
    if collect_coverage == "json":
        return CoverageRunArtifact(coverage_json_path=str(run_dir / "coverage.json"))
    if collect_coverage == "xml":
        return CoverageRunArtifact(coverage_xml_path=str(run_dir / "coverage.xml"))

    return None


def _parse_pytest_counts(output: str) -> tuple[int, int]:
    passed = _sum_count(output, "passed")
    failed = _sum_count(output, "failed")
    return passed, failed


def _sum_count(output: str, status: str) -> int:
    matches = re.findall(rf"(?<!\w)(\d+)\s+{re.escape(status)}(?!\w)", output)
    return sum(int(match) for match in matches)
