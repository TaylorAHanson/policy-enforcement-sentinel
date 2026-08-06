"""The GUI test runner.

The report parsing is tested against XML written by hand, because that is the
part with branches in it. The subprocess is exercised once against a tiny
throwaway suite rather than the real one — running the app's own 350-test suite
from inside itself would be slow and circular.
"""
import asyncio
import os

import pytest

from app.services import pytest_runner


def write_report(tmp_path, body: str) -> str:
    path = tmp_path / "report.xml"
    path.write_text(body, encoding="utf-8")
    return str(path)


# --- Report parsing ---------------------------------------------------------


def test_it_reads_a_bare_testsuite_element(tmp_path):
    """pytest writes <testsuites> on some versions and a bare <testsuite> on
    others, and the difference is invisible until a report comes back empty."""
    report = write_report(
        tmp_path,
        """<?xml version="1.0"?>
        <testsuite name="pytest" tests="2" failures="0" errors="0" skipped="0" time="1.5">
          <testcase classname="tests.test_a" name="test_one" time="0.5"/>
          <testcase classname="tests.test_a" name="test_two" time="1.0"/>
        </testsuite>""",
    )

    result = pytest_runner.parse_junit(report)

    assert result["total"] == 2
    assert result["passed"] == 2
    assert [t["name"] for t in result["tests"]] == ["test_one", "test_two"]


def test_it_reads_a_testsuites_wrapper(tmp_path):
    report = write_report(
        tmp_path,
        """<?xml version="1.0"?>
        <testsuites>
          <testsuite name="pytest" tests="1" failures="0" errors="0" skipped="0" time="0.2">
            <testcase classname="tests.test_a" name="test_one" time="0.2"/>
          </testsuite>
        </testsuites>""",
    )

    assert pytest_runner.parse_junit(report)["total"] == 1


def test_it_separates_failures_errors_and_skips(tmp_path):
    """The three are different things and a runner that lumps them together
    reports a skipped test as a broken one."""
    report = write_report(
        tmp_path,
        """<?xml version="1.0"?>
        <testsuite name="pytest" tests="4" failures="1" errors="1" skipped="1" time="1.0">
          <testcase classname="t" name="ok" time="0.1"/>
          <testcase classname="t" name="broke" time="0.1">
            <failure message="assert 1 == 2">the traceback</failure>
          </testcase>
          <testcase classname="t" name="exploded" time="0.1">
            <error message="fixture blew up">the traceback</error>
          </testcase>
          <testcase classname="t" name="skipped" time="0.0">
            <skipped message="opa not installed"/>
          </testcase>
        </testsuite>""",
    )

    result = pytest_runner.parse_junit(report)
    outcomes = {t["name"]: t["outcome"] for t in result["tests"]}

    assert outcomes == {
        "ok": "passed",
        "broke": "failed",
        "exploded": "error",
        "skipped": "skipped",
    }
    assert result["failed"] == 2
    assert result["skipped"] == 1
    assert result["passed"] == 1


def test_it_keeps_the_failure_message(tmp_path):
    """Without the message the report says a test failed and nothing else,
    which sends you back to the terminal you were trying to avoid."""
    report = write_report(
        tmp_path,
        """<?xml version="1.0"?>
        <testsuite name="pytest" tests="1" failures="1" errors="0" skipped="0" time="0.1">
          <testcase classname="t" name="broke" time="0.1">
            <failure message="assert 'FLAG' == 'WARN'">full traceback here</failure>
          </testcase>
        </testsuite>""",
    )

    detail = pytest_runner.parse_junit(report)["tests"][0]["detail"]

    assert "FLAG" in detail


def test_it_truncates_enormous_tracebacks(tmp_path):
    """The whole report goes over the wire, and a parametrised failure can
    carry a traceback per case."""
    report = write_report(
        tmp_path,
        f"""<?xml version="1.0"?>
        <testsuite name="pytest" tests="1" failures="1" errors="0" skipped="0" time="0.1">
          <testcase classname="t" name="broke" time="0.1">
            <failure message="{'x' * 9000}">body</failure>
          </testcase>
        </testsuite>""",
    )

    assert len(pytest_runner.parse_junit(report)["tests"][0]["detail"]) <= 2000


# --- Suite selection --------------------------------------------------------


def test_it_refuses_an_unknown_suite():
    """The suite name reaches a subprocess command line, so it is chosen from a
    fixed set rather than passed through."""
    with pytest.raises(ValueError):
        asyncio.run(pytest_runner.run("../../etc"))


def test_every_named_suite_is_a_relative_path_inside_the_backend():
    for name, path in pytest_runner.SUITES.items():
        assert not os.path.isabs(path), name
        assert ".." not in path, name


def test_the_safety_suite_points_somewhere_real():
    """This is the CI bug that shipped: the safety step pointed at a directory
    holding only __init__.py, so the gate on the whole non-destructive model ran
    zero tests. Pinning the path here means the runner and CI cannot drift apart
    silently again."""
    path = os.path.join(pytest_runner.backend_dir(), pytest_runner.SUITES["safety"])

    assert os.path.isdir(path)
    assert [f for f in os.listdir(path) if f.startswith("test_")]


# --- Running ----------------------------------------------------------------


def test_it_runs_a_suite_and_reports_the_outcome(tmp_path, monkeypatch):
    """One end-to-end pass over a throwaway suite, so the subprocess wiring and
    the report path are proven together."""
    suite = tmp_path / "tinytests"
    suite.mkdir()
    (suite / "test_tiny.py").write_text(
        "def test_passes():\n"
        "    assert True\n"
        "\n"
        "def test_fails():\n"
        "    assert 1 == 2\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(pytest_runner, "backend_dir", lambda: str(tmp_path))
    monkeypatch.setitem(pytest_runner.SUITES, "tiny", "tinytests")

    result = asyncio.run(pytest_runner.run("tiny"))

    assert result["total"] == 2
    assert result["passed"] == 1
    assert result["failed"] == 1
    assert result["ok"] is False
    assert result["exit_code"] != 0


def test_a_missing_suite_directory_is_not_a_crash(tmp_path, monkeypatch):
    """Suites are trimmed out of the deployed app sometimes; the runner should
    say so rather than raise something that reads as a bug."""
    monkeypatch.setattr(pytest_runner, "backend_dir", lambda: str(tmp_path))
    monkeypatch.setitem(pytest_runner.SUITES, "gone", "not_there")

    with pytest.raises(FileNotFoundError):
        asyncio.run(pytest_runner.run("gone"))


def test_a_collection_error_is_reported_as_a_failure(tmp_path, monkeypatch):
    """A file that will not import must never come back looking like a clean
    run. pytest reports it as an error case rather than a failed assertion, so
    it only counts if errors are counted."""
    suite = tmp_path / "brokentests"
    suite.mkdir()
    (suite / "test_broken.py").write_text("import nonexistent_module_xyz\n", encoding="utf-8")

    monkeypatch.setattr(pytest_runner, "backend_dir", lambda: str(tmp_path))
    monkeypatch.setitem(pytest_runner.SUITES, "broken", "brokentests")

    result = asyncio.run(pytest_runner.run("broken"))

    assert result["ok"] is False
    assert result["passed"] == 0
    assert result["failed"] >= 1 or result.get("error")


def test_a_run_that_produces_no_report_is_not_read_as_success(tmp_path, monkeypatch):
    """The dangerous shape: no XML on disk. Zero of zero tests passing must not
    render as a green run."""
    monkeypatch.setattr(pytest_runner, "backend_dir", lambda: str(tmp_path))
    monkeypatch.setitem(pytest_runner.SUITES, "empty", "emptytests")
    (tmp_path / "emptytests").mkdir()

    result = asyncio.run(pytest_runner.run("empty"))

    assert result["ok"] is False
    assert result["total"] == 0
    assert result.get("error")
