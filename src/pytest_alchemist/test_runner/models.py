"""Models used by test runners."""

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class TestCase:
    """A test known to the minimization pipeline."""

    __test__: ClassVar[bool] = False

    nodeid: str
    file_path: str
    estimated_duration: float


@dataclass(frozen=True)
class CoverageRunArtifact:
    """Coverage artifacts produced by a pytest run."""

    __test__: ClassVar[bool] = False

    coverage_xml_path: str | None = None
    coverage_json_path: str | None = None


@dataclass(frozen=True)
class TestRunResult:
    """Result of running a selected test set."""

    __test__: ClassVar[bool] = False

    selected_tests: list[TestCase | str]
    passed: int
    failed: int
    duration_seconds: float
    exit_code: int
    stdout_path: str | None = None
    stderr_path: str | None = None
    coverage: CoverageRunArtifact | None = None
