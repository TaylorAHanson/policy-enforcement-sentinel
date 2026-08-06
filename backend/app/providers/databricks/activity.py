"""How long since a resource was actually used.

Nine rules across nine resource types ask for ``idle_days``, which reads like a
single property every resource has. It is not. "Idle" means something different
for each of them, and the workspace APIs answer for only three:

===================== ==========================================================
cluster               ``terminated_time``. A running cluster is not idle; a
                      terminated one has been idle since it stopped.
job                   The most recent run. Exact, one small call per job.
dataset               ``last_altered``. This is *not written to*, which is the
                      sense the dataset rule asks about, and is weaker than
                      *not read from*.
===================== ==========================================================

For the other six — apps, dashboards, Genie spaces, Lakebase instances, service
principals and SQL warehouses — the workspace APIs expose creation and edit
timestamps and nothing about use. ``update_time`` on an app is when it was last
deployed, not when anyone last opened it, and a rule that treated the two as the
same would flag every stable, heavily-used app in the estate.

The real answer for those six is ``system.access.audit`` and
``system.query.history``, which record use directly. Reading them requires
``SELECT`` on the ``system`` catalog, which only a metastore admin can grant.
That is a permissions decision rather than a missing collector, and it is
reported as such rather than papered over with a timestamp that means something
else.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

#: How many job-run lookups may be in flight at once. Each is a small call, but
#: an estate with hundreds of jobs shouldn't open hundreds of sockets.
_MAX_CONCURRENT_LOOKUPS = 8


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def days_since_ms(timestamp_ms: Optional[int], *, now_ms: Optional[int] = None) -> Optional[int]:
    """Whole days between an epoch-millisecond timestamp and now.

    ``None`` for a missing or non-positive timestamp — the APIs use ``0`` for
    "never", and turning that into 20,000 idle days would flag the entire
    estate on its first scan.
    """
    if not timestamp_ms or timestamp_ms <= 0:
        return None
    elapsed = (now_ms if now_ms is not None else _now_ms()) - int(timestamp_ms)
    if elapsed < 0:
        # Clock skew between us and the control plane. Not idle.
        return 0
    return elapsed // 86_400_000


def days_since_timestamp(value: Any, *, now_ms: Optional[int] = None) -> Optional[int]:
    """Whole days since an ISO-8601 timestamp string, as ``information_schema``
    returns for ``last_altered``. ``None`` when it cannot be parsed."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        # information_schema hands back "2026-08-04 12:34:56.789" or an ISO
        # string with a zone; both parse once the space is normalised.
        parsed = datetime.fromisoformat(text.replace(" ", "T").replace("Z", "+00:00"))
    except ValueError:
        logger.debug("Could not parse timestamp %r for idle calculation.", text)
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return days_since_ms(int(parsed.timestamp() * 1000), now_ms=now_ms)


def cluster_idle_days(cluster: Any, *, now_ms: Optional[int] = None) -> Optional[int]:
    """Days since a cluster last ran.

    A cluster that is not terminated is in use now, so its idle time is zero.
    A terminated one has been idle since it stopped. Returns ``None`` when the
    cluster is terminated but the API gave no termination time, which is the
    honest answer and leaves the rule quiet.
    """
    state = str(getattr(getattr(cluster, "state", None), "value", "") or getattr(cluster, "state", "") or "")
    if state.upper() != "TERMINATED":
        return 0
    return days_since_ms(getattr(cluster, "terminated_time", None), now_ms=now_ms)


#: How many recent runs to read per job. Enough to see a failure streak that
#: began within the window the rules care about, without paging job history.
_RUN_HISTORY_LIMIT = 25


def _run_ended_ms(run: Any) -> Optional[int]:
    """When a run finished. ``end_time`` is 0 while it is still going."""
    for attribute in ("end_time", "start_time"):
        stamp = getattr(run, attribute, None)
        if stamp:
            return int(stamp)
    return None


def _succeeded(run: Any) -> Optional[bool]:
    """Whether a run succeeded, or ``None`` if it has not finished or we cannot tell.

    Databricks has moved this field twice. ``status.termination_details`` is
    current, ``state.result_state`` is what older workspaces return, and a run
    still in flight has neither.
    """
    status = getattr(run, "status", None)
    termination = getattr(status, "termination_details", None)
    code = getattr(termination, "code", None)
    if code is not None:
        return str(getattr(code, "value", code)).upper() == "SUCCESS"

    state = getattr(run, "state", None)
    result = getattr(state, "result_state", None)
    if result is not None:
        return str(getattr(result, "value", result)).upper() == "SUCCESS"
    return None


async def job_run_history(
    workspace_client,
    job_ids: Iterable[Any],
    *,
    now_ms: Optional[int] = None,
) -> Dict[str, Dict[str, Optional[int]]]:
    """``{job_id: {"idle_days": ..., "failed_consecutively_days": ...}}``.

    One ``list_runs`` call per job with bounded concurrency. The alternative —
    pulling every run in the estate over a long window and folding it down — is
    one call in principle and tens of thousands of rows in practice on a busy
    workspace.

    ``idle_days`` is ``None`` for a job that has never run, rather than its age:
    a job created last week and never run is not "idle for seven days" in the
    sense the rule means, and a retirement rule should not fire on something
    nobody has had a chance to run yet.

    ``failed_consecutively_days`` spans from the oldest run in the current
    unbroken failure streak to now, and is ``None`` unless the most recent
    finished run failed. A job that failed for a month and was then fixed has
    no streak, which is the point.
    """
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_LOOKUPS)
    ids = [str(job_id) for job_id in job_ids]

    async def history(job_id: str) -> Dict[str, Optional[int]]:
        async with semaphore:
            try:
                runs = await asyncio.to_thread(
                    lambda: list(
                        workspace_client.jobs.list_runs(
                            job_id=int(job_id), limit=_RUN_HISTORY_LIMIT
                        )
                    )
                )
            except Exception as e:
                logger.debug("Could not read runs for job %s: %s", job_id, e)
                return {"idle_days": None, "failed_consecutively_days": None}

        # list_runs returns newest first, and unfinished runs carry no verdict.
        finished = [(run, _succeeded(run)) for run in runs]
        finished = [(run, ok) for run, ok in finished if ok is not None]

        idle_days = None
        if runs:
            idle_days = days_since_ms(_run_ended_ms(runs[0]), now_ms=now_ms)

        streak_days = None
        if finished and finished[0][1] is False:
            oldest_failure_ms = None
            for run, ok in finished:
                if ok:
                    break
                ended = _run_ended_ms(run)
                if ended:
                    oldest_failure_ms = ended
            streak_days = days_since_ms(oldest_failure_ms, now_ms=now_ms)

        return {"idle_days": idle_days, "failed_consecutively_days": streak_days}

    results = await asyncio.gather(*(history(job_id) for job_id in ids))
    return dict(zip(ids, results))


def merge_idle_days(resource: Dict[str, Any], idle: Optional[int]) -> Dict[str, Any]:
    """Attach ``idle_days`` only when it is known.

    Omitting the field leaves the rule reading its own default and staying
    quiet, and leaves the diagnosis able to say the field was never collected.
    Writing a placeholder would make an unanswerable question look answered.
    """
    if idle is not None:
        resource["idle_days"] = idle
    return resource


def merge_known(resource: Dict[str, Any], fields: Dict[str, Optional[int]]) -> Dict[str, Any]:
    """Attach each field only where its value is known."""
    for name, value in fields.items():
        if value is not None:
            resource[name] = value
    return resource


__all__ = [
    "cluster_idle_days",
    "days_since_ms",
    "days_since_timestamp",
    "job_run_history",
    "merge_idle_days",
    "merge_known",
]
