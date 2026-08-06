"""Running the Python test suite and reading back what happened.

Always a subprocess, never an in-process ``pytest.main``. Importing the suite
into the running app would start a second application lifespan inside the first
one, share this process's settings and database session with tests that expect
to own them, and leave whatever the tests monkeypatched patched for every
request afterwards. A subprocess has none of those problems, and it can be
killed if it hangs.

The suite is fully mocked — no workspace client, no network — so this is safe to
expose in a deployed app. It is still slow enough (~30s) to want a timeout and a
single-run lock.
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: Long enough for the full suite on a cold cache, short enough that a hung run
#: does not hold the lock all day.
TIMEOUT_SECONDS = 600

#: The suites offered in the UI. Anything not in here is refused, because the
#: argument ends up on a subprocess command line.
SUITES: Dict[str, str] = {
    "all": "tests",
    "unit": "tests/unit",
    "safety": "tests/safety",
    "integration": "tests/integration",
}

_lock = asyncio.Lock()


def backend_dir() -> str:
    """The directory pytest runs from: ``backend/``, three up from this file."""
    here = os.path.abspath(__file__)  # backend/app/services/pytest_runner.py
    return os.path.dirname(os.path.dirname(os.path.dirname(here)))


def _python() -> str:
    """The interpreter to run pytest with.

    ``sys.executable`` is the one running the app, which in the deployed app is
    the one with the dependencies installed. A local venv is picked up the same
    way when the app is started from it.
    """
    import sys

    return sys.executable


def parse_junit(path: str) -> Dict[str, Any]:
    """Read a JUnit XML report into something the UI can render.

    pytest writes either a bare ``<testsuite>`` or a ``<testsuites>`` wrapper
    depending on version, so both are handled.
    """
    tree = ET.parse(path)
    root = tree.getroot()
    suites = [root] if root.tag == "testsuite" else list(root)

    tests: List[Dict[str, Any]] = []
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    duration = 0.0

    for suite in suites:
        for key in totals:
            totals[key] += int(suite.get(key, 0) or 0)
        duration += float(suite.get("time", 0) or 0)

        for case in suite.iter("testcase"):
            outcome = "passed"
            detail = None
            for child in case:
                if child.tag in ("failure", "error"):
                    outcome = "failed" if child.tag == "failure" else "error"
                    detail = (child.get("message") or child.text or "").strip()
                    break
                if child.tag == "skipped":
                    outcome = "skipped"
                    detail = (child.get("message") or "").strip()
                    break

            tests.append(
                {
                    "name": case.get("name", ""),
                    "classname": case.get("classname", ""),
                    "file": case.get("file"),
                    "line": case.get("line"),
                    "time": float(case.get("time", 0) or 0),
                    "outcome": outcome,
                    # Truncated: a full pytest traceback is thousands of
                    # characters and the whole report goes over the wire.
                    "detail": (detail or "")[:2000] or None,
                }
            )

    failed = totals["failures"] + totals["errors"]
    return {
        "total": totals["tests"],
        "passed": totals["tests"] - failed - totals["skipped"],
        "failed": failed,
        "skipped": totals["skipped"],
        "duration_seconds": round(duration, 2),
        "tests": tests,
    }


async def run(suite: str = "all", keyword: Optional[str] = None) -> Dict[str, Any]:
    """Run a suite and return the parsed report.

    Concurrent runs are refused rather than queued. Two pytest processes over
    the same tree fight over the cache directory, and a queued run is a request
    that hangs for a minute with nothing to show for it.
    """
    if suite not in SUITES:
        raise ValueError(f"Unknown suite {suite!r}. Choose one of {sorted(SUITES)}.")

    if _lock.locked():
        raise RuntimeError("A test run is already in progress.")

    async with _lock:
        cwd = backend_dir()
        target = SUITES[suite]

        if not os.path.isdir(os.path.join(cwd, target)):
            raise FileNotFoundError(
                f"The {suite} suite is not present in this deployment ({target})."
            )

        with tempfile.TemporaryDirectory() as tmp:
            report = os.path.join(tmp, "report.xml")
            args = [
                _python(),
                "-m",
                "pytest",
                target,
                f"--junit-xml={report}",
                "-q",
                "--no-header",
                # The app's own cache directory is read-only in the deployed
                # app, and a failed cache write fails the whole run.
                "-p",
                "no:cacheprovider",
            ]
            if keyword:
                args += ["-k", keyword]

            env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

            process = await asyncio.create_subprocess_exec(
                *args,
                cwd=cwd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            try:
                stdout, _ = await asyncio.wait_for(
                    process.communicate(), timeout=TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise TimeoutError(
                    f"The test run exceeded {TIMEOUT_SECONDS}s and was stopped."
                )

            output = (stdout or b"").decode("utf-8", errors="replace")

            if not os.path.exists(report):
                # No report means pytest did not get as far as running
                # anything — a collection error, usually. The output is the
                # only useful thing there is, so it goes back verbatim.
                return {
                    "suite": suite,
                    "ok": False,
                    "total": 0,
                    "passed": 0,
                    "failed": 0,
                    "skipped": 0,
                    "duration_seconds": 0,
                    "tests": [],
                    "exit_code": process.returncode,
                    "output": output[-8000:],
                    "error": "pytest produced no report. It probably failed to collect.",
                }

            result = parse_junit(report)

    result.update(
        {
            "suite": suite,
            "keyword": keyword,
            "exit_code": process.returncode,
            "ok": process.returncode == 0,
            "output": output[-8000:],
        }
    )

    # Exit 5 is "collected nothing". It has to be called out rather than shown
    # as a run of zero tests that did not fail, because that is indistinguishable
    # from a clean pass at a glance — which is how a safety gate pointed at an
    # empty directory survived in CI.
    if process.returncode == 5:
        result["error"] = (
            f"No tests were collected from {SUITES[suite]}"
            + (f" matching {keyword!r}" if keyword else "")
            + ". Nothing ran, so nothing was verified."
        )

    return result
