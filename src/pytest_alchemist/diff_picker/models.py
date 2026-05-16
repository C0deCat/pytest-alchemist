"""Models for changed code selection."""

from dataclasses import dataclass
from typing import ClassVar, Literal

from pytest_alchemist.coverage_analysis.models import CoverageQuality, CoverageRecord
from pytest_alchemist.test_runner.models import TestCase

ChangeKind = Literal["added", "modified", "deleted"]
MatchKind = Literal["raw_line"]
SelectionDiagnosticCode = Literal[
    "no_changed_python_files",
    "no_matching_coverage",
    "coverage_missing",
    "coverage_degraded",
    "deleted_lines_present_but_unmatched_with_current_coverage",
]


@dataclass(frozen=True)
class ChangedCode:
    """Changed line locations in one file."""

    file_path: str
    added_lines: list[int]
    modified_lines: list[int]
    deleted_lines: list[int]

    @property
    def current_lines(self) -> list[int]:
        """Return changed lines that exist in the current source tree."""

        return sorted(set(self.added_lines) | set(self.modified_lines))


@dataclass(frozen=True)
class MatchEvidence:
    """Evidence connecting one test to one changed location."""

    test_nodeid: str
    file_path: str
    line: int
    change_kind: Literal["added", "modified"]
    match_kind: MatchKind


@dataclass(frozen=True)
class SelectionDiagnostics:
    """Structured warnings and reasons produced during selection."""

    codes: list[SelectionDiagnosticCode]
    warnings: list[str]
    coverage_quality: CoverageQuality | None


@dataclass(frozen=True)
class TestSelection:
    """Affected tests and factual evidence selected from a diff."""

    __test__: ClassVar[bool] = False

    candidates: list[TestCase]
    target_changes: list[ChangedCode]
    coverage_records: list[CoverageRecord]
    evidence: list[MatchEvidence]
    diagnostics: SelectionDiagnostics
