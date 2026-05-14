"""Pytest hook plugin for collecting raw per-test reports."""

from __future__ import annotations

import json
import os
from typing import Any

REPORTS_PATH_ENV = "PYTEST_ALCHEMIST_REPORTS_PATH"
PLUGIN_MODULE_NAME = "pytest_alchemist.test_runner.logger"


def pytest_runtest_logreport(report: Any) -> None:
    reports_path = os.environ.get(REPORTS_PATH_ENV)
    if not reports_path:
        return

    payload = {
        "nodeid": report.nodeid,
        "when": report.when,
        "outcome": report.outcome,
        "duration": report.duration,
    }
    with open(reports_path, "a", encoding="utf-8") as file:
        file.write(json.dumps(payload) + "\n")
