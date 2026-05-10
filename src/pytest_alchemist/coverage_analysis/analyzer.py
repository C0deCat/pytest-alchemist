"""Mock coverage analyzer."""

from pytest_alchemist.coverage_analysis.models import CoverageCollectionResult
from pytest_alchemist.database.facade import DatabaseFacade


class CoverageAnalyzer:
    """Collects and parses coverage data.

    The implementation is intentionally mocked for the initial project skeleton.
    """

    def __init__(self, database: DatabaseFacade) -> None:
        self._database = database

    def collect(self) -> CoverageCollectionResult:
        """Return deterministic coverage data and persist the mock collection."""

        records = self._database.list_coverage_records()
        result = CoverageCollectionResult(
            records=records,
            tests=self._database.list_tests(),
            covered_files=sorted({record.file_path for record in records}),
        )
        self._database.save_coverage_collection(records)
        return result
