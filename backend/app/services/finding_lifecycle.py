"""What changed since the last scan.

The dashboard could only ever answer "what is wrong", and on a real estate that
answer is 3,789 violations, of which 3,038 have been identical across all five
scans and exactly one is new. Nobody triages a four-digit list that has not
moved in a month. The questions people actually have — what appeared this week,
what got fixed, what has been sitting open since May — were all unanswerable,
because a finding had no identity: every scan appended a fresh row and nothing
connected the row to the same problem seen last time.

This module gives a finding an identity and a lifecycle. The append-only log
stays exactly as it is and remains the evidence; this is the index into it.

Closing a finding is the whole difficulty
-----------------------------------------

A finding that is absent from a scan has *not* necessarily been fixed. It can
be absent because:

- the rule ran and passed — somebody fixed it;
- the resource was deleted — the finding is moot, and nothing improved;
- a policy was narrowed or retired — we stopped asking, and nothing improved;
- discovery failed to enumerate that resource type at all — we have no idea.

Only the first is good news, and the last is not news at all. Collapsing them
into "resolved" would mean a permissions change that breaks the volume handler
silently closes four hundred findings and reports it as progress. That is the
same shape as the bug found in ``field_reconciliation`` this morning — a check
failing in the reassuring direction — with considerably worse consequences,
because here the reassurance is the product's main output.

So: nothing closes without positive evidence. A scan may only judge findings
whose resource type it successfully enumerated, in a workspace it successfully
reached. Everything else keeps its previous status and simply does not have its
``last_evaluated`` stamp advanced, which is what makes a stale finding
distinguishable from a confirmed one.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from app.db.finding_state import (
    RESOLUTION_FIXED,
    RESOLUTION_NOT_EVALUATED,
    RESOLUTION_RESOURCE_GONE,
    STATUS_OPEN,
    STATUS_RESOLVED,
    SentinelFindingStateModel,
)

logger = logging.getLogger(__name__)


def fingerprint(
    *,
    workspace: Optional[str],
    resource_type: Optional[str],
    resource_id: Optional[str],
    resource_name: Optional[str] = None,
    policy_id: Optional[str] = None,
    policy: Optional[str] = None,
    rule_id: Optional[str] = None,
) -> Optional[str]:
    """A stable identity for "this rule, about this resource, in this workspace".

    ``None`` when there is not enough to identify anything, which is deliberate:
    a finding with no resource and no rule cannot be tracked over time, and
    inventing a fingerprint for it would silently merge every such finding into
    one row.

    The resource type is part of the identity rather than a detail beside it.
    Ids are unique within a type and not across one: a real workspace had
    ``regression-validation-dev`` as both an app and a Lakebase instance, and
    keying on the id alone had already merged those two into a single record
    once, in the fixture capture.

    ``policy_id`` is the stable identifier a rule keeps across edits and
    renames. It falls back to the package and rule name, which are stable enough
    for a policy nobody has renamed, and are all some older findings carry.
    """
    rule = policy_id or (f"{policy}.{rule_id}" if policy and rule_id else rule_id)
    resource = resource_id or resource_name
    if not rule or not resource:
        return None

    parts = [
        (workspace or "").strip().lower(),
        (resource_type or "").strip().lower(),
        str(resource).strip().lower(),
        str(rule).strip().lower(),
    ]
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return digest[:32]


def fingerprint_of(finding) -> Optional[str]:
    """The fingerprint of a ``SentinelFindingModel`` row."""
    return fingerprint(
        workspace=finding.workspace,
        resource_type=finding.resource_type,
        resource_id=finding.resource_id,
        resource_name=finding.resource_name,
        policy_id=finding.policy_id,
        policy=finding.policy,
        rule_id=finding.rule_id,
    )


class ScanCoverage:
    """Which (workspace, resource type) pairs a scan was able to judge.

    Without this, absence is ambiguous and every conclusion drawn from it is
    unsafe. A scan that could not list clusters must not be allowed to conclude
    anything at all about cluster findings — least of all that they are fixed.
    """

    def __init__(self) -> None:
        self._judged: Set[Tuple[str, str]] = set()

    def add(self, workspace: Optional[str], resource_type: Optional[str]) -> None:
        if workspace and resource_type:
            self._judged.add((workspace.lower(), resource_type.lower()))

    def covers(self, workspace: Optional[str], resource_type: Optional[str]) -> bool:
        if not workspace or not resource_type:
            return False
        return (workspace.lower(), resource_type.lower()) in self._judged

    def __len__(self) -> int:
        return len(self._judged)

    @classmethod
    def from_run(cls, run, findings: Iterable = ()) -> "ScanCoverage":
        """Read coverage off a stored run and the findings it produced.

        Coverage requires *positive evidence* that a type was enumerated:
        either the run recorded field observations for it, or it produced at
        least one verdict about a resource of that type. A type listed in the
        workspace's ``errors`` is excluded even when it also returned
        resources, because a partial listing is not a basis for concluding that
        anything is absent.

        The alternative — assuming every registered handler ran unless it
        reported an error — is more complete and less safe. A handler that was
        added after an old run, or one that returned nothing because an API
        quietly changed, would look like a successful enumeration of an empty
        estate, and every finding of that type would close as ``resource_gone``.

        The cost of requiring evidence is one honest gap: a type that really did
        drop to zero resources produces neither observations nor findings, so
        its old findings stay open and unconfirmed rather than closing. They are
        visible as stale, which is the right way for "we cannot currently tell"
        to look.
        """
        coverage = cls()
        results = run.results or {}

        failed_by_workspace: Dict[str, Set[str]] = {}
        for summary in results.get("workspaces") or []:
            if not isinstance(summary, dict):
                continue
            workspace = summary.get("workspace")
            if not workspace or summary.get("status") == "failed":
                continue

            failed = {str(t).lower() for t in (summary.get("errors") or {})}
            failed_by_workspace[workspace] = failed

            observed = (
                (summary.get("field_observations") or {}).get("resource_types") or {}
            )
            for resource_type in observed:
                if str(resource_type).lower() not in failed:
                    coverage.add(workspace, resource_type)

        # Older runs predate field observations, and a verdict about a resource
        # is itself proof that its type was enumerated.
        for finding in findings:
            if finding.kind not in ("violation", "check"):
                continue
            workspace = finding.workspace
            resource_type = finding.resource_type
            if not workspace or not resource_type:
                continue
            if workspace in failed_by_workspace:
                if str(resource_type).lower() in failed_by_workspace[workspace]:
                    continue
            coverage.add(workspace, resource_type)

        return coverage


def _observed(findings: Iterable) -> Tuple[Dict[str, Any], Set[str], Set[str]]:
    """Split one run's findings into violations, passes, and everything seen.

    Returns ``(violations_by_fingerprint, passed, evaluated)``. ``passed`` is the
    positive evidence that closes a finding as fixed; ``evaluated`` is every
    fingerprint the run produced any verdict about, which is what distinguishes
    "the rule ran and said nothing" from "the rule was never run".
    """
    violations: Dict[str, Any] = {}
    passed: Set[str] = set()
    evaluated: Set[str] = set()

    for finding in findings:
        if finding.kind not in ("violation", "check"):
            continue
        key = fingerprint_of(finding)
        if not key:
            continue
        evaluated.add(key)
        if finding.kind == "violation":
            violations[key] = finding
        else:
            passed.add(key)

    # A rule that both fired and passed for one resource in one run should not
    # happen, and if it does the violation is the safe reading.
    passed -= set(violations)
    return violations, passed, evaluated


def _apply(
    state: SentinelFindingStateModel,
    finding,
    *,
    run_id: str,
    at: datetime,
) -> None:
    """Record that this finding is currently true."""
    if state.status == STATUS_RESOLVED:
        state.reopened = (state.reopened or 0) + 1
        state.resolution = None
        state.resolved_at = None
        state.resolved_run = None

    state.status = STATUS_OPEN
    state.workspace = finding.workspace
    state.environment = finding.environment
    state.resource_id = finding.resource_id
    state.resource_type = finding.resource_type
    state.resource_name = finding.resource_name
    state.owner = finding.owner
    state.policy = finding.policy
    state.rule_id = finding.rule_id
    state.policy_id = finding.policy_id
    state.category = finding.category
    state.severity = finding.severity
    state.message = finding.message

    if state.first_seen_at is None:
        state.first_seen_at = at
        state.first_seen_run = run_id

    state.last_seen_at = at
    state.last_seen_run = run_id
    state.last_evaluated_at = at
    state.last_evaluated_run = run_id
    state.occurrences = (state.occurrences or 0) + 1


def _close(
    state: SentinelFindingStateModel,
    *,
    resolution: str,
    run_id: str,
    at: datetime,
) -> None:
    state.status = STATUS_RESOLVED
    state.resolution = resolution
    state.resolved_at = at
    state.resolved_run = run_id
    state.last_evaluated_at = at
    state.last_evaluated_run = run_id


def reconcile_run(db, run, *, coverage: Optional[ScanCoverage] = None) -> Dict[str, int]:
    """Fold one run's findings into the lifecycle table.

    Returns counts of what changed, which is what the interface leads with.
    """
    from app.db.sentinel_finding import SentinelFindingModel

    at = run.started_at or datetime.utcnow()
    run_id = run.id

    findings = (
        db.query(SentinelFindingModel)
        .filter(SentinelFindingModel.run_id == run_id)
        .all()
    )
    if coverage is None:
        coverage = ScanCoverage.from_run(run, findings)

    violations, passed, evaluated = _observed(findings)

    existing = {
        state.fingerprint: state
        for state in db.query(SentinelFindingStateModel).all()
    }

    counts = {
        "new": 0,
        "still_open": 0,
        "fixed": 0,
        "resource_gone": 0,
        "not_evaluated": 0,
        "reopened": 0,
        "unjudgeable": 0,
    }

    for key, finding in violations.items():
        state = existing.get(key)
        if state is None:
            state = SentinelFindingStateModel(fingerprint=key)
            db.add(state)
            existing[key] = state
            counts["new"] += 1
        elif state.status == STATUS_RESOLVED:
            counts["reopened"] += 1
        else:
            counts["still_open"] += 1
        _apply(state, finding, run_id=run_id, at=at)

    for key, state in existing.items():
        if key in violations or state.status == STATUS_RESOLVED:
            continue

        if key in passed:
            # The rule ran against the resource and was satisfied. The only
            # evidence that means somebody fixed something.
            _close(state, resolution=RESOLUTION_FIXED, run_id=run_id, at=at)
            counts["fixed"] += 1
            continue

        if not coverage.covers(state.workspace, state.resource_type):
            # This scan could not see that resource type in that workspace, so
            # it has nothing to say. The finding keeps its status and, crucially,
            # keeps its old `last_evaluated` stamp, which is what lets the
            # interface show it as unconfirmed rather than current.
            counts["unjudgeable"] += 1
            continue

        if key in evaluated:
            # Enumerated and evaluated, produced neither a violation nor a pass.
            # Should not happen; treat it as unjudged rather than as good news.
            counts["unjudgeable"] += 1
            continue

        # The type was enumerated successfully and this resource+rule produced
        # nothing. Either the resource is gone or the rule no longer applies to
        # it. Both close the finding, and they are recorded apart because only
        # a person can tell which, and neither is somebody having fixed it.
        resolution = (
            RESOLUTION_RESOURCE_GONE
            if _resource_absent(state, findings)
            else RESOLUTION_NOT_EVALUATED
        )
        _close(state, resolution=resolution, run_id=run_id, at=at)
        counts[resolution] += 1

    db.commit()
    return counts


def _resource_absent(state: SentinelFindingStateModel, findings: Iterable) -> bool:
    """Whether the run saw this resource at all, under any rule.

    Distinguishes "the cluster is gone" from "the cluster is there and this rule
    stopped applying to it". Both close the finding; only one of them means the
    estate changed.
    """
    target = (state.resource_id or state.resource_name or "").lower()
    if not target:
        return True
    resource_type = (state.resource_type or "").lower()

    for finding in findings:
        if (finding.resource_type or "").lower() != resource_type:
            continue
        seen = (finding.resource_id or finding.resource_name or "").lower()
        if seen == target:
            return False
    return True


def backfill(db, *, limit: int = 200) -> Dict[str, Any]:
    """Build the lifecycle table from the runs already in the database.

    Starting from empty would mean nobody sees a trend until two more scans have
    happened, and the history to answer "how long has this been open" is sitting
    right there. Runs are replayed oldest first so first-seen dates are real
    rather than all being today.
    """
    from app.db.sentinel_run import SentinelRunModel

    runs = (
        db.query(SentinelRunModel)
        .order_by(SentinelRunModel.started_at.asc(), SentinelRunModel.id.asc())
        .limit(limit)
        .all()
    )

    replayed = 0
    for run in runs:
        try:
            reconcile_run(db, run)
            replayed += 1
        except Exception as e:
            logger.warning("Could not replay run %s: %s", run.id, e)
            db.rollback()

    return {
        "runs_replayed": replayed,
        "findings_tracked": db.query(SentinelFindingStateModel).count(),
    }


#: A finding not confirmed by this many scans is reported as unconfirmed rather
#: than as current. One is too eager — a single failed enumeration would grey out
#: half the estate — and beyond three the staleness has stopped being news.
STALE_AFTER_SCANS = 2


def summary(
    db,
    *,
    run_id: Optional[str] = None,
    stale_after: int = STALE_AFTER_SCANS,
) -> Dict[str, Any]:
    """What changed at one scan, for the top of the dashboard.

    The standing total is deliberately not the headline. It is four digits, it
    has not moved in a month, and leading with it is what makes the page
    unreadable: everything looks equally urgent and equally old. What somebody
    can act on is the handful that appeared since last time, the ones that came
    back after being fixed, and the ones nobody has touched the longest.

    ``run_id`` selects which scan to describe, defaulting to the most recent.
    It exists because the dashboard lets you select an older run, and a panel
    pinned to the newest scan sitting above cards describing a different one is
    two contradictory sets of numbers on one screen with nothing saying why.

    Two caveats about older runs, both consequences of this table holding each
    finding's *current* position rather than an event log:

    ``unconfirmed`` is only asked of the newest scan. "Nothing has confirmed
    this lately" is a claim about now; asked of a scan from March it would
    report the whole estate, truthfully and uselessly.

    ``fixed`` and ``returned`` for a past scan report only what is still true.
    A finding fixed at scan 8 that came back at scan 9 no longer counts toward
    scan 8's ``fixed``, because reopening clears ``resolved_run``. So a past
    scan can under-report how much moved, never over-report, and the newest
    scan — the one the dashboard opens on — is always exact. ``appeared`` has
    no such caveat: ``first_seen_run`` is written once and never cleared.
    """
    from app.db.sentinel_run import SentinelRunModel

    runs = (
        db.query(SentinelRunModel)
        .filter(SentinelRunModel.status == "completed")
        .order_by(SentinelRunModel.started_at.desc())
        .all()
    )
    if not runs:
        return {
            "available": False,
            "reason": "No scan has completed yet, so there is nothing to compare.",
        }

    index = 0
    if run_id:
        index = next((i for i, r in enumerate(runs) if r.id == run_id), -1)
        if index < 0:
            return {
                "available": False,
                "reason": "That scan is not in the history, so there is nothing to compare.",
            }

    selected = runs[index]
    previous = runs[index + 1] if index + 1 < len(runs) else None
    is_latest = index == 0
    cutoff = (
        runs[stale_after].started_at
        if is_latest and len(runs) > stale_after
        else None
    )

    states = db.query(SentinelFindingStateModel).all()
    open_states = [s for s in states if s.status == STATUS_OPEN]

    def at_this_run(predicate) -> List[SentinelFindingStateModel]:
        if previous is None:
            return []
        return [s for s in states if predicate(s)]

    appeared = at_this_run(lambda s: s.first_seen_run == selected.id)
    returned = at_this_run(
        lambda s: s.last_seen_run == selected.id
        and (s.reopened or 0) > 0
        and s.first_seen_run != selected.id
    )
    fixed = at_this_run(
        lambda s: s.resolved_run == selected.id and s.resolution == RESOLUTION_FIXED
    )
    gone = at_this_run(
        lambda s: s.resolved_run == selected.id and s.resolution == RESOLUTION_RESOURCE_GONE
    )
    unasked = at_this_run(
        lambda s: s.resolved_run == selected.id and s.resolution == RESOLUTION_NOT_EVALUATED
    )

    # Open, and not confirmed by the last few scans. Distinct from "still a
    # problem": nobody has been able to look. Only asked of the newest scan,
    # because "nothing has confirmed this lately" is a claim about the present.
    unconfirmed = [
        s
        for s in open_states
        if cutoff is not None
        and (s.last_evaluated_at is None or s.last_evaluated_at < cutoff)
    ]

    return {
        "available": True,
        "run_id": selected.id,
        "scanned_at": selected.started_at.isoformat() if selected.started_at else None,
        "compared_to": previous.id if previous else None,
        "compared_to_at": (
            previous.started_at.isoformat() if previous and previous.started_at else None
        ),
        "is_first_scan": previous is None,
        "is_latest": is_latest,
        #: Open *now*, across the whole estate. Deliberately not named ``open``:
        #: sitting among per-run counts, that reads as "open at this scan",
        #: which is not recoverable from current state and is a different number
        #: for every run but this one. Rendering it beside a run's violation
        #: count is what put two contradictory totals on the dashboard.
        "open_now": len(open_states),
        "appeared": _brief(appeared),
        "returned": _brief(returned),
        "fixed": _brief(fixed),
        "resource_gone": _brief(gone),
        "no_longer_checked": _brief(unasked),
        "unconfirmed": _brief(unconfirmed),
        "oldest": _brief(
            sorted(
                (s for s in open_states if s.first_seen_at),
                key=lambda s: s.first_seen_at,
            )[:10],
            cap=10,
        ),
        "by_severity": _counts(open_states, "severity"),
        "by_resource_type": _counts(open_states, "resource_type"),
    }


def _brief(states: List[SentinelFindingStateModel], *, cap: int = 25) -> Dict[str, Any]:
    """A count plus a readable sample. The count is the fact; the sample is so
    somebody can tell at a glance whether it is worth opening."""
    return {
        "count": len(states),
        "items": [
            {
                "fingerprint": s.fingerprint,
                "policy_id": s.policy_id,
                "resource_type": s.resource_type,
                "resource_name": s.resource_name,
                "resource_id": s.resource_id,
                "workspace": s.workspace,
                "owner": s.owner,
                "severity": s.severity,
                "message": s.message,
                "first_seen_at": s.first_seen_at.isoformat() if s.first_seen_at else None,
                "last_seen_at": s.last_seen_at.isoformat() if s.last_seen_at else None,
                "last_evaluated_at": (
                    s.last_evaluated_at.isoformat() if s.last_evaluated_at else None
                ),
                "occurrences": s.occurrences,
                "reopened": s.reopened,
                "resolution": s.resolution,
            }
            for s in states[:cap]
        ],
    }


def _counts(states: List[SentinelFindingStateModel], attribute: str) -> List[Dict[str, Any]]:
    tally: Dict[str, int] = {}
    for state in states:
        tally[str(getattr(state, attribute) or "unknown")] = (
            tally.get(str(getattr(state, attribute) or "unknown"), 0) + 1
        )
    return [
        {"value": value, "count": count}
        for value, count in sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


__all__ = [
    "STALE_AFTER_SCANS",
    "ScanCoverage",
    "backfill",
    "fingerprint",
    "fingerprint_of",
    "reconcile_run",
    "summary",
]
