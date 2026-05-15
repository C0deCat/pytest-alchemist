"""Coverage data models."""

from dataclasses import dataclass
from typing import Literal

from pytest_alchemist.test_runner.models import TestCase

CoverageQuality = Literal[
    "complete",
    "missing_contexts",
    "missing_arcs",
    "unreadable",
    "source_mismatch",
    "partial",
]


@dataclass(frozen=True)
class CoverageRecord:
    """Lines covered by one test in one file."""

    test_nodeid: str
    file_path: str
    lines: list[int]


@dataclass(frozen=True)
class CoverageCollectionResult:
    """Summary returned by a coverage collection scenario."""

    run_uid: str | None
    quality: CoverageQuality
    warnings: list[str]
    entity_count: int
    line_fact_count: int
    arc_fact_count: int
    covered_files: list[str]
    records: list[CoverageRecord]
    tests: list[TestCase]


@dataclass(frozen=True)
class CoverageArtifactMetadata:
    """Metadata about a native Coverage.py data artifact."""

    run_uid: str
    path: str
    sha256: str | None
    coverage_py_version: str | None
    has_contexts: bool
    has_arcs: bool
    quality: CoverageQuality


@dataclass(frozen=True)
class CoverageEntity:
    """Normalized code entity observed during coverage collection."""

    id: int | None
    run_uid: str
    file_path: str
    module_name: str | None
    qualified_name: str | None
    kind: str
    start_line: int | None
    end_line: int | None
    normalized_hash: str | None
    parent_id: int | None


@dataclass(frozen=True)
class CoverageLineFact:
    """A test context executed a line within a normalized entity."""

    run_uid: str
    nodeid: str
    phase: str
    entity_id: int
    raw_line: int
    entity_line_offset: int | None


@dataclass(frozen=True)
class CoverageArcFact:
    """A test context executed a branch arc within a normalized entity."""

    run_uid: str
    nodeid: str
    phase: str
    entity_id: int
    from_line: int
    to_line: int
    from_offset: int | None
    to_offset: int | None
    arc_hash: str
