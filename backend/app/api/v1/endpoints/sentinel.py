"""Sentinel run, findings, and enforcement endpoints.

Runs are returned as summaries with server-side pagination; the findings for a
run are a separate, filtered, paginated endpoint. Returning a run's full
findings inline meant the dashboard downloaded every violation in every run just
to draw a list.

The enforcement endpoints here are the UI's route to the chokepoint, not around
it: ``/preflight`` shows what would happen, ``/approve`` mints a run-scoped
expiring approval, and every action still resolves through
``resolve_effective_action``.
"""
import asyncio
import datetime
import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.actions import ActionTier, describe_ladder, normalize_action, tier_of
from app.core.config import settings
from app.core.enforcement import ScanMode
from app.db.enforcement_audit import EnforcementAuditModel
from app.db.sentinel_finding import SentinelFindingModel
from app.db.sentinel_run import SentinelRunModel
from app.db.session import get_db, get_lakebase_session
from app.services import finding_lifecycle
from app.services.sentinel_service import (
    SentinelService,
    build_approval,
    coerce_mode,
    scan_workspaces,
)

logger = logging.getLogger(__name__)
router = APIRouter()

#: In-memory approvals, keyed by run. They are deliberately not persisted:
#: an approval is meant to be a live confirmation for a run happening now, and
#: surviving a restart would make it a standing permission.
_APPROVALS: Dict[str, Any] = {}


def _serialize_run(run: SentinelRunModel, include_results: bool = True) -> Dict[str, Any]:
    payload = {
        "id": run.id,
        "workspace": run.workspace,
        "environment": run.environment,
        "mode": run.mode,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "error": run.error,
        "total_resources": run.total_resources or 0,
        "violation_count": run.violation_count or 0,
        "check_count": run.check_count or 0,
        "remediated_count": run.remediated_count or 0,
        "downgraded_count": run.downgraded_count or 0,
        "approved_by": run.approved_by,
    }
    if include_results:
        payload["results"] = run.results
    return payload


def _serialize_finding(finding: SentinelFindingModel) -> Dict[str, Any]:
    return {
        "id": finding.id,
        "run_id": finding.run_id,
        "kind": finding.kind,
        "workspace": finding.workspace,
        "environment": finding.environment,
        "resource_id": finding.resource_id,
        "resource_type": finding.resource_type,
        "resource_name": finding.resource_name,
        "owner": finding.owner,
        "policy": finding.policy,
        "rule_id": finding.rule_id,
        "policy_id": finding.policy_id,
        "category": finding.category,
        "severity": finding.severity,
        "message": finding.message,
        "requested_action": finding.requested_action,
        "effective_action": finding.effective_action,
        "tier": finding.tier,
        "requested_tier": finding.requested_tier,
        "downgraded": bool(
            finding.requested_action
            and finding.effective_action
            and finding.requested_action != finding.effective_action
        ),
        "downgrade_reason": finding.downgrade_reason,
        "executed": bool(finding.executed),
        "data": finding.data,
        "created_at": finding.created_at.isoformat() if finding.created_at else None,
    }


# --- Runs -------------------------------------------------------------------


@router.get("/runs")
async def get_runs(
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=200),
    search: Optional[str] = None,
    status: Optional[str] = None,
    summary: bool = Query(True, description="Omit the results blob for list rendering"),
    db: Session = Depends(get_db),
):
    query = db.query(SentinelRunModel)

    if status:
        query = query.filter(SentinelRunModel.status == status)
    if search:
        pattern = f"%{search.lower()}%"
        query = query.filter(
            or_(
                func.lower(SentinelRunModel.workspace).like(pattern),
                func.lower(SentinelRunModel.environment).like(pattern),
                func.lower(SentinelRunModel.id).like(pattern),
            )
        )

    total = query.count()
    runs = (
        query.order_by(SentinelRunModel.started_at.desc()).offset(skip).limit(limit).all()
    )

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "runs": [_serialize_run(r, include_results=not summary) for r in runs],
    }


@router.get("/runs/{run_id}")
async def get_run(run_id: str, db: Session = Depends(get_db)):
    run = db.query(SentinelRunModel).filter(SentinelRunModel.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _serialize_run(run)


def _filtered_findings(
    db: Session,
    run_id: str,
    *,
    kind: Optional[str] = None,
    severity: Optional[str] = None,
    category: Optional[str] = None,
    resource_type: Optional[str] = None,
    effective_action: Optional[str] = None,
    downgraded_only: bool = False,
    search: Optional[str] = None,
    exclude: Optional[str] = None,
):
    """The findings query the list and the facet counts share.

    ``exclude`` drops one dimension, which is what a facet needs: the count
    beside "Reliability" should say how many results choosing it would give,
    so it has to respect the other filters while ignoring the category
    selection itself.
    """
    query = db.query(SentinelFindingModel).filter(SentinelFindingModel.run_id == run_id)

    if kind and exclude != "kind":
        query = query.filter(SentinelFindingModel.kind == kind)
    if severity and exclude != "severity":
        query = query.filter(SentinelFindingModel.severity == severity)
    if category and exclude != "category":
        query = query.filter(SentinelFindingModel.category == category)
    if resource_type and exclude != "resource_type":
        query = query.filter(SentinelFindingModel.resource_type == resource_type)
    if effective_action and exclude != "effective_action":
        query = query.filter(
            SentinelFindingModel.effective_action == effective_action
        )
    if downgraded_only and exclude != "downgraded_only":
        query = query.filter(
            SentinelFindingModel.requested_action != SentinelFindingModel.effective_action
        )
    if search and exclude != "search":
        query = query.filter(SentinelFindingModel.search_text.like(f"%{search.lower()}%"))

    return query


@router.get("/runs/{run_id}/findings")
async def get_run_findings(
    run_id: str,
    kind: Optional[str] = None,
    severity: Optional[str] = None,
    category: Optional[str] = None,
    resource_type: Optional[str] = None,
    effective_action: Optional[str] = None,
    downgraded_only: bool = False,
    search: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    query = _filtered_findings(
        db,
        run_id,
        kind=kind,
        severity=severity,
        category=category,
        resource_type=resource_type,
        effective_action=effective_action,
        downgraded_only=downgraded_only,
        search=search,
    )

    total = query.count()
    findings = (
        query.order_by(SentinelFindingModel.severity, SentinelFindingModel.id)
        .offset(skip)
        .limit(limit)
        .all()
    )

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "findings": [_serialize_finding(f) for f in findings],
    }


@router.get("/runs/{run_id}/facets")
async def get_run_facets(
    run_id: str,
    kind: Optional[str] = None,
    severity: Optional[str] = None,
    category: Optional[str] = None,
    resource_type: Optional[str] = None,
    effective_action: Optional[str] = None,
    downgraded_only: bool = False,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Distinct filter values with counts, against the currently filtered set.

    Counting the whole run instead made every number describe a population the
    reader was not looking at: with Violations and Reliability selected the menu
    read 2276 beside Reliability while the tab beside it said 757, the
    difference being the reliability checks that passed.
    """
    filters = {
        "kind": kind,
        "severity": severity,
        "category": category,
        "resource_type": resource_type,
        "effective_action": effective_action,
        "downgraded_only": downgraded_only,
        "search": search,
    }

    def _facet(column, dimension: Optional[str] = None):
        rows = (
            _filtered_findings(db, run_id, **filters, exclude=dimension)
            .with_entities(column, func.count(SentinelFindingModel.id))
            .group_by(column)
            .all()
        )
        return [{"value": value, "count": count} for value, count in rows if value]

    return {
        "severity": _facet(SentinelFindingModel.severity, "severity"),
        "category": _facet(SentinelFindingModel.category, "category"),
        "resource_type": _facet(SentinelFindingModel.resource_type, "resource_type"),
        # No filter of their own, so these simply follow the current selection.
        "policy": _facet(SentinelFindingModel.policy),
        "policy_id": _facet(SentinelFindingModel.policy_id),
        "effective_action": _facet(
            SentinelFindingModel.effective_action, "effective_action"
        ),
    }


@router.get("/changes")
async def changes(
    run_id: Optional[str] = Query(None, description="Defaults to the most recent scan."),
    db: Session = Depends(get_db),
):
    """What changed at one scan, relative to the one before it.

    Every other view here is scoped to one run and answers "what is wrong",
    which on a real estate is 3,789 violations that have barely moved in a
    month. Nobody triages that. This answers "what changed", which on the same
    estate is one new finding — a number somebody can actually act on.

    ``run_id`` follows whichever run the dashboard has selected. Without it the
    panel described the newest scan while the cards beside it described an older
    one, which is two sets of correct numbers contradicting each other on one
    screen.
    """
    try:
        return finding_lifecycle.summary(db, run_id=run_id)
    except Exception as e:
        logger.exception("Could not summarise finding changes.")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/changes/rebuild")
async def rebuild_changes(db: Session = Depends(get_db)):
    """Rebuild the lifecycle table from the findings log.

    The table is derived, so it can always be reconstructed from the runs that
    are already stored. That makes it safe to lose and worth being able to
    repair without a scan — which matters on first upgrade, when the history is
    sitting there and starting from empty would mean no trend data until two
    more scans have happened.
    """
    try:
        return finding_lifecycle.backfill(db)
    except Exception as e:
        logger.exception("Could not rebuild the finding lifecycle table.")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/runs")
async def purge_runs(
    older_than_days: int = Query(30, ge=1), db: Session = Depends(get_db)
):
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=older_than_days)
    stale = db.query(SentinelRunModel).filter(SentinelRunModel.started_at < cutoff).all()
    run_ids = [r.id for r in stale]

    if run_ids:
        db.query(SentinelFindingModel).filter(
            SentinelFindingModel.run_id.in_(run_ids)
        ).delete(synchronize_session=False)
        db.query(SentinelRunModel).filter(SentinelRunModel.id.in_(run_ids)).delete(
            synchronize_session=False
        )
        db.commit()

    return {"purged": len(run_ids), "older_than_days": older_than_days}


# --- Triggering a scan ------------------------------------------------------


class RunRequest(BaseModel):
    mode: str = "audit"
    workspaces: Optional[List[str]] = None
    approval_id: Optional[str] = None


@router.post("/run")
async def trigger_run(
    background_tasks: BackgroundTasks,
    mode: str = "audit",
    payload: Optional[RunRequest] = None,
    db: Session = Depends(get_db),
):
    requested_mode = coerce_mode((payload.mode if payload else None) or mode)
    workspaces = settings.get_workspaces()

    if payload and payload.workspaces:
        wanted = set(payload.workspaces)
        workspaces = [w for w in workspaces if w.get("name") in wanted]
        if not workspaces:
            raise HTTPException(status_code=400, detail="No matching workspaces configured")

    names = [w.get("name", "unknown") for w in workspaces]
    run_id = str(uuid.uuid4())

    approval = None
    if requested_mode is ScanMode.ENFORCE:
        # Enforce mode without a live, matching approval is not silently
        # downgraded here — it is refused, because the operator asked for
        # something specific and should be told they didn't get it.
        pending = _APPROVALS.get(payload.approval_id) if payload and payload.approval_id else None
        if pending is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Enforce mode requires an approval. Call "
                    "POST /sentinel/enforcement/approve first and pass the approval_id."
                ),
            )
        approval = build_approval(
            run_id, pending["approved_by"], pending["workspace"]
        )

    run_record = SentinelRunModel(
        id=run_id,
        workspace=", ".join(names),
        environment="multiple" if len(names) > 1 else (
            workspaces[0].get("environment", "prod") if workspaces else "unknown"
        ),
        mode=requested_mode.value,
        status="running",
        started_at=datetime.datetime.utcnow(),
        approved_by=approval.approved_by if approval else None,
        approval_id=approval.approval_id if approval else None,
    )
    db.add(run_record)
    db.commit()

    def _do_run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                scan_workspaces(
                    workspaces, mode=requested_mode, run_id=run_id, approval=approval
                )
            )
            _finish_run(run_id, result)
        except Exception as e:
            logger.exception("Sentinel run %s failed", run_id)
            _fail_run(run_id, str(e))
        finally:
            loop.close()

    background_tasks.add_task(_do_run)
    return {
        "message": f"Run started in {requested_mode.value} mode across {len(workspaces)} workspace(s)",
        # One id covers every workspace in the scan: they are one run, which is
        # what makes the totals on the dashboard add up.
        "run_id": run_id,
        "mode": requested_mode.value,
        #: Named so the operator can see which workspaces were actually matched,
        #: rather than assuming the filter they typed selected what they meant.
        "workspaces": names,
    }


def _finish_run(run_id: str, result: Dict[str, Any]) -> None:
    db = get_lakebase_session()
    try:
        run = db.query(SentinelRunModel).filter(SentinelRunModel.id == run_id).first()
        if not run:
            return
        run.status = result.get("status", "completed")
        run.total_resources = result.get("total_resources", 0)
        run.violation_count = result.get("violations", 0)
        run.check_count = result.get("checks", 0)
        run.remediated_count = result.get("remediated", 0)
        run.downgraded_count = result.get("downgraded", 0)
        # A summary only. The findings themselves are their own rows.
        run.results = {
            "status": result.get("status"),
            "mode": result.get("mode"),
            "total_resources": result.get("total_resources", 0),
            "violations": result.get("violations", 0),
            "checks": result.get("checks", 0),
            "remediated": result.get("remediated", 0),
            "downgraded": result.get("downgraded", 0),
            "workspaces": result.get("workspaces", []),
        }
        run.completed_at = datetime.datetime.utcnow()
        db.commit()

        # Fold this run's findings into the lifecycle table, so the next thing
        # anybody looks at can say what changed rather than restating a
        # four-digit total that has not moved in weeks.
        #
        # Deliberately after the commit and in its own try: a failure here must
        # not lose the run. The lifecycle table is derived and can be rebuilt
        # from the findings log by `finding_lifecycle.backfill`, so losing it is
        # recoverable in a way that losing a scan is not.
        try:
            counts = finding_lifecycle.reconcile_run(db, run)
            logger.info("Run %s lifecycle: %s", run_id, counts)
        except Exception as e:
            logger.error("Could not reconcile findings for run %s: %s", run_id, e)
            db.rollback()
    except Exception as e:
        logger.error("Could not record the completion of run %s: %s", run_id, e)
        db.rollback()
    finally:
        db.close()


def _fail_run(run_id: str, error: str) -> None:
    db = get_lakebase_session()
    try:
        run = db.query(SentinelRunModel).filter(SentinelRunModel.id == run_id).first()
        if run:
            run.status = "failed"
            run.error = error
            run.completed_at = datetime.datetime.utcnow()
            db.commit()
    except Exception as e:
        logger.error("Could not record the failure of run %s: %s", run_id, e)
    finally:
        db.close()


# --- Enforcement ------------------------------------------------------------


class PreflightRequest(BaseModel):
    run_id: str
    mode: str = "enforce"


@router.post("/enforcement/preflight")
async def enforcement_preflight(payload: PreflightRequest, db: Session = Depends(get_db)):
    """What would happen if this run's findings were enforced right now.

    Built from an existing audit run's findings, so an operator sees the real
    blast radius against real data before enabling anything.
    """
    findings = (
        db.query(SentinelFindingModel)
        .filter(
            SentinelFindingModel.run_id == payload.run_id,
            SentinelFindingModel.kind == "violation",
        )
        .all()
    )

    by_tier: Dict[int, List[Dict[str, Any]]] = {}
    workspaces = set()

    for finding in findings:
        requested = normalize_action(finding.requested_action)
        if not requested:
            continue
        tier = int(tier_of(requested))
        by_tier.setdefault(tier, []).append(
            {
                "resource_id": finding.resource_id,
                "resource_type": finding.resource_type,
                "resource_name": finding.resource_name,
                "owner": finding.owner,
                "policy": finding.policy,
                "policy_id": finding.policy_id,
                "requested_action": requested,
                "workspace": finding.workspace,
            }
        )
        workspaces.add(finding.workspace)

    destructive_count = len(by_tier.get(int(ActionTier.DESTRUCTIVE), []))
    cap = settings.DESTRUCTIVE_ACTION_MAX_RESOURCES

    return {
        "run_id": payload.run_id,
        "workspaces": sorted(workspaces),
        "by_tier": [
            {
                "tier": tier,
                "count": len(items),
                "resources": items[:200],
                "truncated": len(items) > 200,
            }
            for tier, items in sorted(by_tier.items(), reverse=True)
        ],
        "destructive_count": destructive_count,
        "blast_radius_limit": cap,
        "exceeds_blast_radius": destructive_count > cap,
        "enforcement_enabled": bool(settings.ENFORCEMENT_ENABLED),
        "allowed_workspaces": settings.destructive_workspaces(),
        "action_ladder": describe_ladder(),
    }


class ApprovalRequest(BaseModel):
    workspace: str
    approved_by: str
    #: The operator types the workspace name to confirm. Checked server-side so
    #: the confirmation is a real gate rather than a UI courtesy.
    confirm_workspace: str


@router.post("/enforcement/approve")
async def approve_enforcement(payload: ApprovalRequest):
    if payload.confirm_workspace.strip() != payload.workspace.strip():
        raise HTTPException(
            status_code=400,
            detail="Confirmation does not match the workspace name.",
        )

    if payload.workspace not in settings.destructive_workspaces():
        raise HTTPException(
            status_code=400,
            detail=(
                f"{payload.workspace} is not in DESTRUCTIVE_ACTION_WORKSPACES. Add it in "
                "Settings before approving enforcement there."
            ),
        )

    approval_id = str(uuid.uuid4())
    _APPROVALS[approval_id] = {
        "workspace": payload.workspace,
        "approved_by": payload.approved_by,
        "created_at": datetime.datetime.utcnow(),
    }
    logger.warning(
        "Enforcement approved for %s by %s (approval %s).",
        payload.workspace,
        payload.approved_by,
        approval_id,
    )
    return {
        "approval_id": approval_id,
        "workspace": payload.workspace,
        "expires_in_minutes": settings.ENFORCEMENT_APPROVAL_TTL_MINUTES,
    }


class EnforcementActionRequest(BaseModel):
    resource_id: str
    resource_type: str
    action: str
    policy_name: Optional[str] = None
    reason: str = "Manual execution via UI"
    workspace: Optional[str] = None


@router.post("/runs/{run_id}/enforcement-action")
async def execute_enforcement_action(
    run_id: str, payload: EnforcementActionRequest, db: Session = Depends(get_db)
):
    run = db.query(SentinelRunModel).filter(SentinelRunModel.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    workspace = payload.workspace or run.workspace
    ws_config = next(
        (w for w in settings.get_workspaces() if w.get("name") == workspace), None
    )

    service = SentinelService(workspace_config=ws_config)
    result = await service.execute_manual_action(
        payload.action,
        payload.resource_type,
        payload.resource_id,
        workspace=workspace,
        reason=payload.reason,
        run_id=run_id,
    )

    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@router.get("/audit")
async def list_audit(
    run_id: Optional[str] = None,
    undoable_only: bool = False,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(EnforcementAuditModel)
    if run_id:
        query = query.filter(EnforcementAuditModel.run_id == run_id)
    if undoable_only:
        query = query.filter(
            EnforcementAuditModel.outcome == "succeeded",
            EnforcementAuditModel.undone_at.is_(None),
            EnforcementAuditModel.undo_payload.isnot(None),
        )

    total = query.count()
    rows = (
        query.order_by(EnforcementAuditModel.started_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return {
        "total": total,
        "entries": [
            {
                "id": row.id,
                "run_id": row.run_id,
                "workspace": row.workspace,
                "resource_id": row.resource_id,
                "resource_type": row.resource_type,
                "policy": row.policy,
                "requested_action": row.requested_action,
                "effective_action": row.effective_action,
                "tier": row.tier,
                "downgrade_reason": row.downgrade_reason,
                "outcome": row.outcome,
                "error": row.error,
                "undoable": row.is_undoable,
                "undone_at": row.undone_at.isoformat() if row.undone_at else None,
                "started_at": row.started_at.isoformat() if row.started_at else None,
            }
            for row in rows
        ],
    }


class UndoRequest(BaseModel):
    undone_by: Optional[str] = None


@router.post("/actions/{audit_id}/undo")
async def undo_enforcement_action(
    audit_id: int, payload: UndoRequest = None, db: Session = Depends(get_db)
):
    from app.providers.databricks.handlers import HANDLER_REGISTRY
    from app.services.action_executor import ActionExecutionError, undo_action

    row = db.query(EnforcementAuditModel).get(audit_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Audit record not found")

    handler_class = HANDLER_REGISTRY.get(row.resource_type)
    if handler_class is None:
        raise HTTPException(
            status_code=400, detail=f"No handler for {row.resource_type}"
        )

    ws_config = next(
        (w for w in settings.get_workspaces() if w.get("name") == row.workspace), None
    )
    service = SentinelService(workspace_config=ws_config)

    try:
        handler = handler_class(service.db_provider.client)
        return await undo_action(
            audit_id, handler, undone_by=(payload.undone_by if payload else None)
        )
    except ActionExecutionError as e:
        raise HTTPException(status_code=400, detail=str(e))
