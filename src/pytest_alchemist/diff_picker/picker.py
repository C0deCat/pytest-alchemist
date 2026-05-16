"""Committed-history diff selection."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from pytest_alchemist.database.facade import DatabaseFacade
from pytest_alchemist.diff_picker.models import (
    ChangedCode,
    MatchEvidence,
    SelectionDiagnosticCode,
    SelectionDiagnostics,
    TestSelection,
)

_HUNK_HEADER = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
)


class DiffRangeError(ValueError):
    """Raised when a requested committed-history range cannot be resolved."""


class DiffPicker:
    """Select every test that factually touched changed current code."""

    def __init__(self, database: DatabaseFacade) -> None:
        self._database = database

    def pick_candidates(self, last_commits: int) -> TestSelection:
        """Return tests affected by Python changes in `HEAD~N..HEAD`."""

        target_changes = self._read_recent_changes(last_commits)
        coverage_records = self._database.list_coverage_records()
        coverage_quality = self._database.get_latest_coverage_quality()
        diagnostics = _build_initial_diagnostics(target_changes, coverage_quality)

        evidence = self._collect_raw_line_evidence(target_changes)
        if (
            target_changes
            and any(change.current_lines for change in target_changes)
            and not evidence
            and "coverage_missing" not in diagnostics.codes
        ):
            diagnostics.codes.append("no_matching_coverage")
            diagnostics.warnings.append(
                "No current coverage facts overlap the changed current lines."
            )

        matching_test_nodeids = {item.test_nodeid for item in evidence}
        candidates = sorted(
            (
                test
                for test in self._database.list_tests()
                if test.nodeid in matching_test_nodeids
            ),
            key=lambda test: test.nodeid,
        )

        return TestSelection(
            candidates=candidates,
            target_changes=target_changes,
            coverage_records=coverage_records,
            evidence=evidence,
            diagnostics=diagnostics,
        )

    def _read_recent_changes(self, last_commits: int) -> list[ChangedCode]:
        range_start = f"HEAD~{last_commits}"
        self._run_git(["rev-parse", "--verify", range_start], range_start)
        completed = self._run_git(
            [
                "diff",
                "--unified=0",
                "--no-color",
                "--no-ext-diff",
                "--no-renames",
                f"{range_start}..HEAD",
                "--",
                "*.py",
            ],
            range_start,
        )
        return _parse_unified_diff(completed.stdout)

    def _run_git(
        self,
        args: list[str],
        range_start: str,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git", *args],
                cwd=self._database.project_path,
                check=True,
                capture_output=True,
                text=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as error:
            raise DiffRangeError(
                f"Could not inspect committed history range {range_start}..HEAD."
            ) from error

    def _collect_raw_line_evidence(
        self,
        target_changes: list[ChangedCode],
    ) -> list[MatchEvidence]:
        evidence: list[MatchEvidence] = []
        for change in target_changes:
            line_kinds = {
                **{line: "added" for line in change.added_lines},
                **{line: "modified" for line in change.modified_lines},
            }
            matches_by_line = self._database.list_tests_covering_lines(
                change.file_path,
                sorted(line_kinds),
            )
            for line in sorted(matches_by_line):
                for nodeid in matches_by_line[line]:
                    evidence.append(
                        MatchEvidence(
                            test_nodeid=nodeid,
                            file_path=change.file_path,
                            line=line,
                            change_kind=line_kinds[line],
                            match_kind="raw_line",
                        )
                    )
        return sorted(
            evidence,
            key=lambda item: (
                item.test_nodeid,
                item.file_path,
                item.line,
                item.change_kind,
            ),
        )


@dataclass
class _MutableChangedCode:
    file_path: str
    added_lines: list[int]
    modified_lines: list[int]
    deleted_lines: list[int]

    def freeze(self) -> ChangedCode:
        return ChangedCode(
            file_path=self.file_path,
            added_lines=sorted(set(self.added_lines)),
            modified_lines=sorted(set(self.modified_lines)),
            deleted_lines=sorted(set(self.deleted_lines)),
        )


def _build_initial_diagnostics(
    target_changes: list[ChangedCode],
    coverage_quality: str | None,
) -> SelectionDiagnostics:
    codes: list[SelectionDiagnosticCode] = []
    warnings: list[str] = []

    if not target_changes:
        codes.append("no_changed_python_files")
        warnings.append("No changed Python files were found in the requested commits.")

    if coverage_quality is None:
        codes.append("coverage_missing")
        warnings.append("No normalized coverage data is available for selection.")
    elif coverage_quality != "complete":
        codes.append("coverage_degraded")
        warnings.append(f"Latest coverage data is degraded: quality={coverage_quality}.")

    if any(change.deleted_lines for change in target_changes):
        codes.append("deleted_lines_present_but_unmatched_with_current_coverage")
        warnings.append(
            "Deleted lines were present, but current-only coverage cannot match them reliably."
        )

    return SelectionDiagnostics(
        codes=codes,
        warnings=warnings,
        coverage_quality=coverage_quality,
    )


def _parse_unified_diff(diff_text: str) -> list[ChangedCode]:
    """Parse a unified Git diff into current- and old-side Python changes."""

    changes_by_file: dict[str, _MutableChangedCode] = {}
    current_change: _MutableChangedCode | None = None
    old_path: str | None = None
    hunk_lines: list[str] = []
    old_line = 0
    new_line = 0

    def flush_hunk() -> None:
        nonlocal hunk_lines, old_line, new_line
        if current_change is None or not hunk_lines:
            hunk_lines = []
            return

        added_lines: list[int] = []
        deleted_lines: list[int] = []
        current_old_line = old_line
        current_new_line = new_line

        for line in hunk_lines:
            if line.startswith("+") and not line.startswith("+++"):
                added_lines.append(current_new_line)
                current_new_line += 1
            elif line.startswith("-") and not line.startswith("---"):
                deleted_lines.append(current_old_line)
                current_old_line += 1
            elif not line.startswith("\\"):
                current_old_line += 1
                current_new_line += 1

        if deleted_lines and added_lines:
            current_change.modified_lines.extend(added_lines)
        else:
            current_change.added_lines.extend(added_lines)
        current_change.deleted_lines.extend(deleted_lines)
        hunk_lines = []

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            flush_hunk()
            current_change = None
            old_path = None
            continue

        if line.startswith("--- "):
            flush_hunk()
            old_path_value = line[4:]
            old_path = old_path_value[2:] if old_path_value.startswith("a/") else None
            continue

        if line.startswith("+++ "):
            flush_hunk()
            new_path = line[4:]
            if new_path == "/dev/null":
                if old_path is None or not old_path.endswith(".py"):
                    current_change = None
                    continue
                current_change = changes_by_file.setdefault(
                    old_path,
                    _MutableChangedCode(
                        file_path=old_path,
                        added_lines=[],
                        modified_lines=[],
                        deleted_lines=[],
                    ),
                )
                continue
            if not new_path.startswith("b/"):
                current_change = None
                continue
            file_path = new_path[2:]
            if not file_path.endswith(".py"):
                current_change = None
                continue
            current_change = changes_by_file.setdefault(
                file_path,
                _MutableChangedCode(
                    file_path=file_path,
                    added_lines=[],
                    modified_lines=[],
                    deleted_lines=[],
                ),
            )
            continue

        hunk_match = _HUNK_HEADER.match(line)
        if hunk_match:
            flush_hunk()
            old_line = int(hunk_match.group("old_start"))
            new_line = int(hunk_match.group("new_start"))
            continue

        if current_change is not None and (
            line.startswith("+") or line.startswith("-") or line.startswith(" ")
        ):
            hunk_lines.append(line)

    flush_hunk()
    return [
        changes_by_file[file_path].freeze()
        for file_path in sorted(changes_by_file)
        if (
            changes_by_file[file_path].added_lines
            or changes_by_file[file_path].modified_lines
            or changes_by_file[file_path].deleted_lines
        )
    ]
