"""Idleness, where it can honestly be measured.

Nine rules asked for `idle_days` as though every resource had one. Three do.
The tests here pin both halves of that: the arithmetic for the three, and the
refusal to invent a number for the rest.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.providers.databricks import activity

NOW = int(datetime(2026, 8, 6, tzinfo=timezone.utc).timestamp() * 1000)
DAY = 86_400_000


class Stub:
    def __init__(self, **fields):
        self.__dict__.update(fields)


# --- The arithmetic ---------------------------------------------------------


def test_days_since_counts_whole_days():
    assert activity.days_since_ms(NOW - 90 * DAY, now_ms=NOW) == 90


def test_a_never_timestamp_is_not_twenty_thousand_idle_days():
    """The APIs use 0 for "never". Treated as an epoch date it becomes 1970,
    which would flag every resource in the estate on the first scan."""
    assert activity.days_since_ms(0, now_ms=NOW) is None
    assert activity.days_since_ms(None, now_ms=NOW) is None


def test_a_future_timestamp_reads_as_not_idle():
    """Clock skew between us and the control plane, not a negative idleness."""
    assert activity.days_since_ms(NOW + 5 * DAY, now_ms=NOW) == 0


def test_an_information_schema_timestamp_parses():
    """`last_altered` comes back space-separated, not ISO-T."""
    assert activity.days_since_timestamp("2026-07-07 00:00:00", now_ms=NOW) == 30
    assert activity.days_since_timestamp("2026-07-07T00:00:00Z", now_ms=NOW) == 30


def test_an_unparseable_timestamp_is_unknown_rather_than_zero():
    assert activity.days_since_timestamp("whenever", now_ms=NOW) is None
    assert activity.days_since_timestamp("", now_ms=NOW) is None


# --- Clusters ---------------------------------------------------------------


def test_a_running_cluster_is_not_idle():
    """Whatever `terminated_time` holds, a cluster that is up is in use."""
    cluster = Stub(state=Stub(value="RUNNING"), terminated_time=NOW - 400 * DAY)
    assert activity.cluster_idle_days(cluster, now_ms=NOW) == 0


def test_a_terminated_cluster_is_idle_since_it_stopped():
    cluster = Stub(state=Stub(value="TERMINATED"), terminated_time=NOW - 120 * DAY)
    assert activity.cluster_idle_days(cluster, now_ms=NOW) == 120


def test_a_terminated_cluster_with_no_stop_time_is_unknown():
    """Not zero. Zero would say "in use", which is the opposite of what we know."""
    cluster = Stub(state=Stub(value="TERMINATED"), terminated_time=None)
    assert activity.cluster_idle_days(cluster, now_ms=NOW) is None


# --- Jobs -------------------------------------------------------------------


class FakeJobs:
    def __init__(self, runs_by_job):
        self.runs_by_job = runs_by_job

    def list_runs(self, job_id, limit):
        return self.runs_by_job.get(job_id, [])[:limit]


def run(days_ago, *, succeeded=True):
    return Stub(
        end_time=NOW - days_ago * DAY,
        start_time=NOW - days_ago * DAY,
        status=Stub(termination_details=Stub(code="SUCCESS" if succeeded else "DRIVER_ERROR")),
    )


def history_for(runs_by_job):
    client = Stub(jobs=FakeJobs(runs_by_job))
    return asyncio.run(
        activity.job_run_history(client, list(runs_by_job), now_ms=NOW)
    )


def test_a_job_is_idle_since_its_last_run():
    assert history_for({1: [run(120)]})["1"]["idle_days"] == 120


def test_a_job_that_has_never_run_reports_no_idleness():
    """A job created last week and never run is not "idle for seven days" in
    the sense the retirement rule means, and should not be retired for it."""
    assert history_for({1: []})["1"]["idle_days"] is None


def test_an_unreadable_job_reports_nothing_rather_than_zero():
    class Exploding:
        def list_runs(self, job_id, limit):
            raise RuntimeError("403")

    result = asyncio.run(
        activity.job_run_history(Stub(jobs=Exploding()), [7], now_ms=NOW)
    )
    assert result["7"] == {"idle_days": None, "failed_consecutively_days": None}


def test_a_failure_streak_spans_to_its_oldest_failure():
    runs = [run(1, succeeded=False), run(20, succeeded=False), run(42, succeeded=False)]
    assert history_for({1: runs})["1"]["failed_consecutively_days"] == 42


def test_a_streak_that_was_fixed_is_not_a_streak():
    """The most recent run succeeded, so there is nothing ongoing to report —
    even though the three before it failed for six weeks."""
    runs = [run(1), run(20, succeeded=False), run(42, succeeded=False)]
    assert history_for({1: runs})["1"]["failed_consecutively_days"] is None


def test_an_older_success_ends_the_streak():
    """Only the unbroken run of failures counts, not every failure on record."""
    runs = [run(1, succeeded=False), run(5, succeeded=False), run(60), run(90, succeeded=False)]
    assert history_for({1: runs})["1"]["failed_consecutively_days"] == 5


def test_a_run_still_in_flight_does_not_decide_the_streak():
    """An unfinished run has no verdict. Reading it as a failure would invent a
    streak; reading it as a success would clear a real one."""
    in_flight = Stub(end_time=0, start_time=NOW, status=Stub(termination_details=None), state=None)
    runs = [in_flight, run(20, succeeded=False), run(42, succeeded=False)]
    assert history_for({1: runs})["1"]["failed_consecutively_days"] == 42


def test_the_older_result_state_shape_is_understood():
    """Databricks moved this field; older workspaces still return the old one."""
    legacy = Stub(
        end_time=NOW - 40 * DAY,
        start_time=NOW - 40 * DAY,
        status=None,
        state=Stub(result_state="FAILED"),
    )
    assert history_for({1: [legacy]})["1"]["failed_consecutively_days"] == 40


# --- Merging ----------------------------------------------------------------


@pytest.mark.parametrize("value", [None])
def test_an_unknown_value_is_left_off_the_resource(value):
    """Absence lets the rule read its own default and stay quiet, and lets the
    diagnosis report the field as never collected. A placeholder would make an
    unanswerable question look answered."""
    assert activity.merge_idle_days({"id": "x"}, value) == {"id": "x"}
    assert activity.merge_known({"id": "x"}, {"idle_days": value}) == {"id": "x"}


def test_a_known_value_is_attached():
    assert activity.merge_idle_days({"id": "x"}, 0) == {"id": "x", "idle_days": 0}
