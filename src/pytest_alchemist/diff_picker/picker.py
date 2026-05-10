"""Mock diff picker."""

from pytest_alchemist.database.facade import DatabaseFacade
from pytest_alchemist.diff_picker.models import TestSelection


class DiffPicker:
    """Selects candidate tests that touched changed code."""

    def __init__(self, database: DatabaseFacade) -> None:
        self._database = database

    def pick_candidates(self, last_commits: int) -> TestSelection:
        """Return candidates related to mocked changed lines."""

        target_changes = self._database.get_recent_changes(last_commits)
        coverage_records = self._database.list_coverage_records()
        changed_lines_by_file = {
            change.file_path: set(change.lines) for change in target_changes
        }
        matching_test_nodeids = {
            record.test_nodeid
            for record in coverage_records
            if changed_lines_by_file.get(record.file_path, set()).intersection(
                record.lines
            )
        }
        candidates = [
            test
            for test in self._database.list_tests()
            if test.nodeid in matching_test_nodeids
        ]

        return TestSelection(
            candidates=candidates,
            target_changes=target_changes,
            coverage_records=coverage_records,
        )
