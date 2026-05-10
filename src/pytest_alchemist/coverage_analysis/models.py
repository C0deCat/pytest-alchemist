"""Coverage data models."""

from dataclasses import dataclass

from pytest_alchemist.test_runner.models import TestCase


@dataclass(frozen=True)
class CoverageRecord:
    """Lines covered by one test in one file."""

    test_nodeid: str
    file_path: str
    lines: list[int]


@dataclass(frozen=True)
class CoverageCollectionResult:
    """Summary returned by a coverage collection scenario."""

    records: list[CoverageRecord]
    tests: list[TestCase]
    covered_files: list[str]
