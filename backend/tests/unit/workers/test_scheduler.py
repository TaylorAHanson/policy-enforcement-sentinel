"""The unattended path.

The scheduler is the only route to an action with nobody watching, so the tests
that matter most here are about what it *cannot* do: it never constructs an
approval, and it never stops running because one scan went wrong.
"""
from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.core.enforcement import ScanMode
from app.db.sentinel_run import SentinelRunModel
from app.workers import scheduler


@pytest.fixture
def fake_scan(monkeypatch):
    """Replace the scan engine and record how it was called."""
    calls = []

    async def _scan(workspaces, *, mode, run_id=None, approval=None):
        calls.append(
            {
                "workspaces": list(workspaces),
                "mode": mode,
                "run_id": run_id,
                "approval": approval,
            }
        )
        return {
            "run_id": run_id,
            "status": "completed",
            "total_resources": 12,
            "violations": 3,
            "checks": 9,
            "remediated": 1,
            "downgraded": 2,
            "workspaces": [
                {"workspace": "prod", "status": "completed", "violations": 3, "errors": {}}
            ],
        }

    monkeypatch.setattr(scheduler, "scan_workspaces", _scan)
    return calls


@pytest.fixture
def one_workspace(monkeypatch):
    # Patched on the class: Settings is a pydantic model and rejects setting an
    # attribute that is not a declared field.
    monkeypatch.setattr(
        type(settings),
        "get_workspaces",
        lambda self: [{"name": "prod", "environment": "prod"}],
    )


# --- What a scheduled run cannot do -----------------------------------------


@pytest.mark.asyncio
async def test_a_scheduled_run_never_carries_an_approval(
    app_db, fake_scan, one_workspace, monkeypatch
):
    """There is nobody to name at 3am, so the approval gate must stay shut."""
    monkeypatch.setattr(settings, "SENTINEL_CRON_MODE", "enforce")

    await scheduler.run_scheduled_scan(run_id="sched-1")

    assert fake_scan[0]["approval"] is None


def test_the_scheduler_cannot_build_an_approval():
    """Structural, so it stays true for code nobody has written yet."""
    source = inspect.getsource(scheduler)
    assert "build_approval" not in source
    assert "EnforcementApproval" not in source


@pytest.mark.asyncio
async def test_an_unrecognised_mode_falls_back_to_audit(
    app_db, fake_scan, one_workspace, monkeypatch
):
    monkeypatch.setattr(settings, "SENTINEL_CRON_MODE", "obliterate")

    await scheduler.run_scheduled_scan(run_id="sched-2")

    assert fake_scan[0]["mode"] == ScanMode.AUDIT


@pytest.mark.asyncio
async def test_the_configured_mode_is_used(
    app_db, fake_scan, one_workspace, monkeypatch
):
    monkeypatch.setattr(settings, "SENTINEL_CRON_MODE", "remediate")

    await scheduler.run_scheduled_scan(run_id="sched-3")

    assert fake_scan[0]["mode"] == ScanMode.REMEDIATE


# --- The run record ---------------------------------------------------------


@pytest.mark.asyncio
async def test_the_run_is_recorded_before_the_scan_starts(
    app_db, db_session, one_workspace, monkeypatch
):
    """A crashed scan must leave a "running" row, not no row at all."""
    seen = {}

    async def _scan(workspaces, *, mode, run_id=None, approval=None):
        row = (
            db_session.query(SentinelRunModel)
            .filter(SentinelRunModel.id == run_id)
            .first()
        )
        seen["status"] = row.status if row else None
        raise RuntimeError("workspace unreachable")

    monkeypatch.setattr(scheduler, "scan_workspaces", _scan)

    with pytest.raises(RuntimeError):
        await scheduler.run_scheduled_scan(run_id="sched-4")

    assert seen["status"] == "running"


@pytest.mark.asyncio
async def test_a_failed_scan_marks_the_run_failed(
    app_db, db_session, one_workspace, monkeypatch
):
    async def _scan(workspaces, *, mode, run_id=None, approval=None):
        raise RuntimeError("workspace unreachable")

    monkeypatch.setattr(scheduler, "scan_workspaces", _scan)

    with pytest.raises(RuntimeError):
        await scheduler.run_scheduled_scan(run_id="sched-5")

    row = db_session.query(SentinelRunModel).filter_by(id="sched-5").first()
    assert row.status == "failed"
    assert "workspace unreachable" in row.error
    assert row.completed_at is not None


@pytest.mark.asyncio
async def test_the_counts_reach_the_run_record(
    app_db, db_session, fake_scan, one_workspace
):
    """The old worker read a key the engine no longer returns, so every
    scheduled run recorded zero violations."""
    await scheduler.run_scheduled_scan(run_id="sched-6")

    row = db_session.query(SentinelRunModel).filter_by(id="sched-6").first()
    assert row.status == "completed"
    assert row.total_resources == 12
    assert row.violation_count == 3
    assert row.check_count == 9
    assert row.remediated_count == 1
    assert row.downgraded_count == 2


@pytest.mark.asyncio
async def test_the_run_record_stores_a_summary_not_every_finding(
    app_db, db_session, fake_scan, one_workspace
):
    """Findings are rows. Duplicating them into JSON is what made the record
    too large to load."""
    await scheduler.run_scheduled_scan(run_id="sched-7")

    row = db_session.query(SentinelRunModel).filter_by(id="sched-7").first()
    assert set(row.results) == {"workspaces"}
    assert row.results["workspaces"][0]["violations"] == 3
    assert "findings" not in row.results


# --- The loop ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_schedule_idles_instead_of_exiting(monkeypatch, caplog):
    """The worker has to outlive an empty schedule.

    The expression is editable in Settings. A worker that returns when it finds
    no schedule at boot leaves nothing running to notice one being saved, so
    turning scheduling on in the UI would appear to work and never fire.
    """
    monkeypatch.setattr(settings, "SENTINEL_CRON_SCHEDULE", None)
    monkeypatch.setattr(scheduler, "TICK_SECONDS", 0.01)

    with caplog.at_level("INFO"):
        task = asyncio.create_task(scheduler.start_scheduler())
        await asyncio.sleep(0.05)

        assert not task.done(), "the scheduler exited on an empty schedule"

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert any("disabled" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_an_invalid_cron_expression_does_not_crash_the_app(monkeypatch, caplog):
    monkeypatch.setattr(settings, "SENTINEL_CRON_SCHEDULE", "not a cron")
    monkeypatch.setattr(scheduler, "TICK_SECONDS", 0.01)

    with caplog.at_level("ERROR"):
        task = asyncio.create_task(scheduler.start_scheduler())
        await asyncio.sleep(0.05)

        # Idles rather than dying, so correcting the typo in Settings recovers
        # without a restart.
        assert not task.done()

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert any("not a valid cron" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_an_invalid_expression_is_logged_once_not_every_tick(monkeypatch, caplog):
    """An error per tick would bury the log at two lines a minute."""
    monkeypatch.setattr(settings, "SENTINEL_CRON_SCHEDULE", "not a cron")
    monkeypatch.setattr(scheduler, "TICK_SECONDS", 0.01)

    with caplog.at_level("ERROR"):
        task = asyncio.create_task(scheduler.start_scheduler())
        await asyncio.sleep(0.08)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    complaints = [r for r in caplog.records if "not a valid cron" in r.message]
    assert len(complaints) == 1


class _DueImmediately:
    """A croniter stand-in whose first next-time has already passed.

    A real ``* * * * *`` fires on the next minute boundary, so asserting
    against it would mean a test that sometimes waits 60 seconds. Only the
    time arithmetic is faked here — the arming path under test is the real one.
    """

    def __init__(self, expression, start):
        self.expression = expression
        self.calls = 0

    def get_next(self, _type):
        self.calls += 1
        if self.calls == 1:
            return datetime.now(timezone.utc) - timedelta(seconds=1)
        return datetime.now(timezone.utc) + timedelta(hours=1)


@pytest.mark.asyncio
async def test_a_schedule_saved_in_settings_arms_the_running_worker(monkeypatch):
    """The whole point of exposing the schedule in Settings.

    Without this, saving a schedule writes a value that nothing acts on until
    the next deploy.
    """
    monkeypatch.setattr(settings, "SENTINEL_CRON_SCHEDULE", None)
    monkeypatch.setattr(scheduler, "TICK_SECONDS", 0.01)
    monkeypatch.setattr(scheduler, "croniter", _DueImmediately)

    ran = asyncio.Event()

    async def _scan(run_id=None):
        ran.set()
        return {}

    monkeypatch.setattr(scheduler, "run_scheduled_scan", _scan)

    task = asyncio.create_task(scheduler.start_scheduler())
    await asyncio.sleep(0.05)
    assert not ran.is_set(), "scanned with no schedule set"

    monkeypatch.setattr(settings, "SENTINEL_CRON_SCHEDULE", "0 2 * * *")

    try:
        await asyncio.wait_for(ran.wait(), timeout=2)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_clearing_the_schedule_disarms_the_running_worker(monkeypatch):
    """Turning scheduling off has to take effect without a restart too."""
    monkeypatch.setattr(settings, "SENTINEL_CRON_SCHEDULE", "0 2 * * *")
    monkeypatch.setattr(scheduler, "TICK_SECONDS", 0.01)
    monkeypatch.setattr(scheduler, "croniter", _DueImmediately)

    scans = {"n": 0}

    async def _scan(run_id=None):
        scans["n"] += 1
        return {}

    monkeypatch.setattr(scheduler, "run_scheduled_scan", _scan)

    task = asyncio.create_task(scheduler.start_scheduler())
    await asyncio.wait_for(_until(lambda: scans["n"] >= 1), timeout=2)

    monkeypatch.setattr(settings, "SENTINEL_CRON_SCHEDULE", "")
    await asyncio.sleep(0.05)
    settled = scans["n"]
    await asyncio.sleep(0.05)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert scans["n"] == settled, "kept scanning after the schedule was cleared"


async def _until(predicate, interval: float = 0.01) -> None:
    while not predicate():
        await asyncio.sleep(interval)


@pytest.mark.asyncio
async def test_a_failing_scan_does_not_end_the_schedule(monkeypatch):
    """The old loop exited on the first exception and scheduled scanning
    stopped for good."""
    attempts = {"n": 0}

    async def _failing_scan(run_id=None):
        attempts["n"] += 1
        if attempts["n"] >= 3:
            raise asyncio.CancelledError()
        raise RuntimeError("scan blew up")

    monkeypatch.setattr(settings, "SENTINEL_CRON_SCHEDULE", "* * * * *")
    monkeypatch.setattr(scheduler, "run_scheduled_scan", _failing_scan)
    monkeypatch.setattr(scheduler, "TICK_SECONDS", 0)

    # Always due, so the loop fires every tick.
    class AlwaysDue:
        def __init__(self, *args, **kwargs):
            pass

        def get_next(self, _type):
            return datetime.now(timezone.utc)

    monkeypatch.setattr(scheduler, "croniter", AlwaysDue)

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(scheduler.start_scheduler(), timeout=5)

    assert attempts["n"] == 3, "the loop stopped after a failure"


@pytest.mark.asyncio
async def test_the_next_time_advances_before_the_scan_runs(monkeypatch):
    """Otherwise a scan that outlives its interval fires again immediately."""
    order = []

    class RecordingCron:
        def __init__(self, *args, **kwargs):
            self.n = 0

        def get_next(self, _type):
            self.n += 1
            order.append(f"advance-{self.n}")
            return datetime.now(timezone.utc)

    async def _scan(run_id=None):
        order.append("scan")
        raise asyncio.CancelledError()

    monkeypatch.setattr(settings, "SENTINEL_CRON_SCHEDULE", "* * * * *")
    monkeypatch.setattr(scheduler, "croniter", RecordingCron)
    monkeypatch.setattr(scheduler, "run_scheduled_scan", _scan)
    monkeypatch.setattr(scheduler, "TICK_SECONDS", 0)

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(scheduler.start_scheduler(), timeout=5)

    assert order == ["advance-1", "advance-2", "scan"]


@pytest.mark.asyncio
async def test_cancellation_stops_the_loop(monkeypatch):
    """Shutdown must not be swallowed by the retry handler."""
    monkeypatch.setattr(settings, "SENTINEL_CRON_SCHEDULE", "0 * * * *")
    monkeypatch.setattr(scheduler, "TICK_SECONDS", 0.01)

    task = asyncio.create_task(scheduler.start_scheduler())
    await asyncio.sleep(0.05)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
