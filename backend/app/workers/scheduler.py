"""The cron worker that runs unattended scans.

This is the only path that acts without a human present, which shapes two
decisions here:

* **No approval is ever constructed.** A destructive action needs a run-scoped
  approval carrying the name of the person who granted it, and there is nobody
  to name at three in the morning. So a scheduled run in ``enforce`` mode still
  passes through every gate and still fails the approval one. Raising the mode
  widens what a scheduled run may do up to Tier 2; Tier 3 stays out of reach
  from here by construction.

* **One bad iteration must not end the schedule.** The failure the previous
  version had was quiet: an exception escaped the loop, the task exited, and
  scheduled scanning stopped for good with nothing but a single line in a log
  nobody reads. The loop body is now wrapped, and a failure sleeps and retries.

The loop also wakes on a short interval and compares against the next cron time
rather than sleeping until it, so a settings change or a clock jump is picked up
within one tick instead of at the end of a multi-hour sleep. That includes the
cron expression itself: it is admin-editable, so it is re-read each tick and the
loop stays alive even when no schedule is set.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from croniter import croniter

from app.core.config import settings
from app.db.sentinel_run import SentinelRunModel
from app.services.sentinel_service import coerce_mode, scan_workspaces

logger = logging.getLogger(__name__)


def _session():
    """Resolved per call, like everywhere else that touches the database.

    Binding the factory at import time would hold one session across a
    multi-hour wait, and an idle-timeout drop would then take the next scan with
    it.
    """
    from app.db.session import get_lakebase_session

    return get_lakebase_session()

#: How often the loop wakes to check whether the next cron time has passed.
TICK_SECONDS = 30

#: How long to wait after an unexpected failure before trying again. Longer than
#: a tick so a persistent fault does not spin.
ERROR_BACKOFF_SECONDS = 60


def _record_start(run_id: str, workspaces, mode: str, started: datetime) -> None:
    names = [w.get("name", "unknown") for w in workspaces]
    db = _session()
    try:
        db.add(
            SentinelRunModel(
                id=run_id,
                workspace=", ".join(names),
                environment=(
                    "multiple"
                    if len(workspaces) > 1
                    else (workspaces[0].get("environment", "prod") if workspaces else "prod")
                ),
                mode=mode,
                status="running",
                started_at=started,
            )
        )
        db.commit()
    finally:
        db.close()


def _record_finish(run_id: str, results: dict) -> None:
    """Store the summary only.

    The findings are rows in ``sentinel_findings``. Writing them into the run's
    JSON column as well was what made a large run's record too big to load.
    """
    db = _session()
    try:
        run = db.query(SentinelRunModel).filter(SentinelRunModel.id == run_id).first()
        if run is None:
            logger.error("Run %s vanished before it could be completed.", run_id)
            return

        run.status = results.get("status", "completed")
        run.completed_at = datetime.now(timezone.utc)
        run.total_resources = results.get("total_resources", 0)
        run.violation_count = results.get("violations", 0)
        run.check_count = results.get("checks", 0)
        run.remediated_count = results.get("remediated", 0)
        run.downgraded_count = results.get("downgraded", 0)
        run.results = {
            "workspaces": [
                {
                    "workspace": w.get("workspace"),
                    "status": w.get("status"),
                    "errors": w.get("errors") or {},
                    "violations": w.get("violations", 0),
                }
                for w in results.get("workspaces", [])
            ]
        }
        db.commit()
    finally:
        db.close()


def _record_failure(run_id: str, error: str) -> None:
    db = _session()
    try:
        run = db.query(SentinelRunModel).filter(SentinelRunModel.id == run_id).first()
        if run is None:
            return
        run.status = "failed"
        run.error = error
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as e:  # pragma: no cover - the database is already unhappy
        logger.error("Could not record the failure of run %s: %s", run_id, e)
        db.rollback()
    finally:
        db.close()


async def run_scheduled_scan(run_id: Optional[str] = None) -> dict:
    """One scheduled scan. Separated from the loop so it can be tested and
    triggered by hand."""
    run_id = run_id or str(uuid.uuid4())
    mode = coerce_mode(settings.SENTINEL_CRON_MODE)
    workspaces = settings.get_workspaces()
    started = datetime.now(timezone.utc)

    logger.info(
        "Scheduled scan %s starting in %s mode across %d workspace(s).",
        run_id,
        mode.value,
        len(workspaces),
    )

    _record_start(run_id, workspaces, mode.value, started)

    try:
        # No approval argument. A scheduled run cannot name the person who
        # authorised a destructive action, so it cannot pass that gate.
        results = await scan_workspaces(workspaces, mode=mode, run_id=run_id)
    except Exception as e:
        logger.error("Scheduled scan %s failed: %s", run_id, e, exc_info=True)
        _record_failure(run_id, f"{type(e).__name__}: {e}")
        raise

    _record_finish(run_id, results)
    logger.info(
        "Scheduled scan %s finished: %s, %d violation(s), %d remediated, %d downgraded.",
        run_id,
        results.get("status"),
        results.get("violations", 0),
        results.get("remediated", 0),
        results.get("downgraded", 0),
    )
    return results


async def start_scheduler() -> None:
    """Run scans on ``SENTINEL_CRON_SCHEDULE`` until cancelled.

    The expression is re-read every tick rather than captured once. It is
    admin-editable in Settings, and capturing it meant a schedule set in the UI
    did nothing until the next restart — with the worse case being no schedule
    at boot, where this coroutine used to return immediately and leave nothing
    running to notice the setting ever changed.

    So the loop always runs. An unset or invalid expression idles rather than
    exits, and starts scanning the moment a valid one is saved.
    """
    # None means "not yet evaluated"; the empty string is a real, disabled
    # state, so the two cannot share a sentinel.
    applied: Optional[str] = None
    cron = None
    next_run: Optional[datetime] = None

    while True:
        try:
            schedule = (settings.SENTINEL_CRON_SCHEDULE or "").strip()

            # Only rebuild when the expression actually changed, so the log
            # gets one line per change rather than one per tick.
            if schedule != applied:
                applied, cron, next_run = schedule, None, None

                if not schedule:
                    logger.info(
                        "Scheduled scans are disabled (SENTINEL_CRON_SCHEDULE is unset)."
                    )
                else:
                    try:
                        cron = croniter(schedule, datetime.now(timezone.utc))
                        next_run = cron.get_next(datetime)
                        logger.info(
                            "Scheduler armed with cron %r in %s mode. Next run: %s",
                            schedule,
                            settings.SENTINEL_CRON_MODE,
                            next_run,
                        )
                    except Exception as e:
                        cron, next_run = None, None
                        logger.error(
                            "SENTINEL_CRON_SCHEDULE %r is not a valid cron expression: %s",
                            schedule,
                            e,
                        )

            if cron is not None and next_run is not None:
                if datetime.now(timezone.utc) >= next_run:
                    # Advanced before the scan rather than after, so a scan that
                    # outlives its own interval schedules from the right base
                    # instead of firing again the instant it finishes.
                    next_run = cron.get_next(datetime)
                    try:
                        await run_scheduled_scan()
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        # Already logged with a traceback, and already recorded
                        # on the run. The schedule survives it.
                        logger.warning("Scheduled scan failed; the schedule continues.")
                    logger.info("Next scheduled scan: %s", next_run)

            await asyncio.sleep(TICK_SECONDS)
        except asyncio.CancelledError:
            logger.info("Scheduler stopped.")
            raise
        except Exception as e:
            logger.error("Scheduler loop error: %s", e, exc_info=True)
            await asyncio.sleep(ERROR_BACKOFF_SECONDS)
