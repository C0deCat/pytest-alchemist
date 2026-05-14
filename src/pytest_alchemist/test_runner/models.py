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
