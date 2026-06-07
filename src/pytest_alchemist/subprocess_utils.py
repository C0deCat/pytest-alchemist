"""Internal subprocess helpers."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from typing import Any


def run_captured_text(
    args: Sequence[str | os.PathLike[str]],
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """Run a command and decode captured output independently of locale."""

    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **kwargs,
    )
