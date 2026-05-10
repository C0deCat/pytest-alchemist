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
class TestRunResult:
    """Result of running a selected test set."""

    selected_tests: list[TestCase]
    passed: int
    failed: int
    duration_seconds: float
    exit_code: int
