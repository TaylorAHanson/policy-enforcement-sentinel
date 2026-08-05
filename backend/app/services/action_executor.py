"""Executes a resolved action against a resource, with an audit trail.

Every caller — the scan engine, a manual action from the UI, an MCP tool — goes
through :func:`execute_action`. It refuses anything that didn't come from
``resolve_effective_action``, so there is no route to a handler's destructive
methods that skipped the gates.

The audit row is written **before** the handler runs. If the process dies
halfway through a termination, the surviving record says what was attempted;
writing it afterwards would mean the actions that went most wrong are exactly
the ones with no trace.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from app.core.actions import ActionTier, get_spec
from app.core.enforcement import EffectiveAction
from app.db.enforcement_audit import EnforcementAuditModel
from app.providers.databricks.handlers.base import supports

logger = logging.getLogger(__name__)


class ActionExecutionError(RuntimeError):
    """The action could not be carried out. The audit row records why."""


def _session():
    from app.db.session import get_lakebase_session

    return get_lakebase_session()


def record_intent(
    effective: EffectiveAction,
    *,
    workspace: str,
    resource_id: str,
    resource_type: str,
    run_id: Optional[str] = None,
    policy: Optional[str] = None,
    policy_id: Optional[str] = None,
    approved_by: Optional[str] = None,
    approval_id: Optional[str] = None,
) -> Optional[int]:
    """Write the pre-execution audit row. Returns its id."""
    db = _session()
    try:
        row = EnforcementAuditModel(
            run_id=run_id,
            workspace=workspace,
            resource_id=str(resource_id),
            resource_type=resource_type,
            policy=policy,
            policy_id=policy_id,
            requested_action=effective.requested_action,
            effective_action=effective.action,
            tier=int(effective.tier),
            downgrade_reason=effective.downgrade_reason,
            mode=effective.mode.value,
            outcome="intent",
            approved_by=approved_by,
            approval_id=approval_id,
            started_at=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    except Exception as e:
        # A failure to audit must not become a silent action. The caller treats
        # a missing audit id as a reason to stop.
        logger.error("Could not write the enforcement audit intent row: %s", e)
        return None
    finally:
        db.close()


def _finalize(
    audit_id: Optional[int],
    outcome: str,
    *,
    error: Optional[str] = None,
    undo_payload: Optional[Dict[str, Any]] = None,
) -> None:
    if audit_id is None:
        return

    db = _session()
    try:
        row = db.query(EnforcementAuditModel).get(audit_id)
        if row is None:
            return
        row.outcome = outcome
        row.error = error
        row.completed_at = datetime.utcnow()
        if undo_payload is not None:
            row.undo_payload = undo_payload
        db.commit()
    except Exception as e:
        logger.error("Could not finalise audit row %s: %s", audit_id, e)
    finally:
        db.close()


async def execute_action(
    handler,
    effective: EffectiveAction,
    *,
    workspace: str,
    resource_id: str,
    resource_type: str,
    message: str = "",
    owner: Optional[str] = None,
    run_id: Optional[str] = None,
    policy: Optional[str] = None,
    policy_id: Optional[str] = None,
    approved_by: Optional[str] = None,
    approval_id: Optional[str] = None,
    audit: bool = True,
) -> Dict[str, Any]:
    """Carry out a resolved action. The only sanctioned way to act on a resource."""
    if not isinstance(effective, EffectiveAction) or not effective.is_authorized():
        raise ActionExecutionError(
            "execute_action requires an EffectiveAction from resolve_effective_action(). "
            "Actions cannot be self-authorised."
        )

    spec = get_spec(effective.action)
    if spec is None:
        raise ActionExecutionError(f"Unknown action {effective.action!r}")

    # Tier 0 has nothing to do; the finding is the whole outcome.
    if spec.handler_method is None:
        return {"executed": False, "action": effective.action, "audit_id": None}

    verb = spec.handler_method
    if not supports(handler, verb):
        # Should be unreachable: the chokepoint is told what the handler
        # supports. Reaching here means the two disagreed, which is worth an
        # error rather than a silent no-op.
        logger.error(
            "Handler %s does not implement %r for the resolved action %s.",
            type(handler).__name__,
            verb,
            effective.action,
        )
        return {
            "executed": False,
            "action": effective.action,
            "error": f"handler does not support {verb}",
            "audit_id": None,
        }

    audit_id = (
        record_intent(
            effective,
            workspace=workspace,
            resource_id=resource_id,
            resource_type=resource_type,
            run_id=run_id,
            policy=policy,
            policy_id=policy_id,
            approved_by=approved_by,
            approval_id=approval_id,
        )
        if audit
        else None
    )

    if audit and audit_id is None and effective.tier >= ActionTier.RESTRICT:
        # No audit row means no undo payload and no record. For anything that
        # changes a resource, that is reason enough not to proceed.
        raise ActionExecutionError(
            f"Refusing to perform {effective.action} on {resource_id}: the audit "
            "record could not be written."
        )

    method = getattr(handler, verb)
    try:
        if verb == "warn":
            result = await method(resource_id, message, owner)
        elif verb == "annotate":
            result = await method(resource_id, message, authorization=effective)
        elif spec.tier >= ActionTier.DESTRUCTIVE:
            result = await method(resource_id, authorization=effective)
        else:
            result = await method(resource_id, authorization=effective)
    except Exception as e:
        logger.error(
            "Action %s failed on %s %s: %s: %s",
            effective.action,
            resource_type,
            resource_id,
            type(e).__name__,
            e,
        )
        _finalize(audit_id, "failed", error=f"{type(e).__name__}: {e}")
        return {
            "executed": False,
            "action": effective.action,
            "error": str(e),
            "audit_id": audit_id,
        }

    # Tier 2 verbs return the prior state; that is what makes them undoable.
    undo_payload = result if isinstance(result, dict) else None
    if spec.tier == ActionTier.RESTRICT and undo_payload is None:
        logger.warning(
            "%s on %s returned no undo payload; the action cannot be reversed "
            "automatically.",
            effective.action,
            resource_id,
        )

    _finalize(audit_id, "succeeded", undo_payload=undo_payload)
    return {
        "executed": True,
        "action": effective.action,
        "undo_payload": undo_payload,
        "audit_id": audit_id,
    }


async def undo_action(audit_id: int, handler, *, undone_by: Optional[str] = None) -> Dict[str, Any]:
    """Reverse a previously executed Tier 2 action."""
    db = _session()
    try:
        row = db.query(EnforcementAuditModel).get(audit_id)
        if row is None:
            raise ActionExecutionError(f"No audit record {audit_id}")
        if row.undone_at is not None:
            raise ActionExecutionError(f"Action {audit_id} was already undone")
        if row.outcome != "succeeded":
            raise ActionExecutionError(
                f"Action {audit_id} did not succeed ({row.outcome}); there is nothing to undo"
            )

        spec = get_spec(row.effective_action)
        if spec is None or spec.undo_method is None:
            raise ActionExecutionError(
                f"{row.effective_action} is not reversible. Tier 3 actions are "
                "irreversible by definition — that is why they sit behind five gates."
            )

        undo_payload = row.undo_payload or {}
        resource_id = row.resource_id
        undo_method = spec.undo_method
    finally:
        db.close()

    if not supports(handler, undo_method):
        raise ActionExecutionError(
            f"Handler {type(handler).__name__} does not implement {undo_method}"
        )

    await getattr(handler, undo_method)(resource_id, undo_payload)

    db = _session()
    try:
        row = db.query(EnforcementAuditModel).get(audit_id)
        row.undone_at = datetime.utcnow()
        row.undone_by = undone_by
        db.commit()
    finally:
        db.close()

    logger.info("Undid %s on %s (audit %s).", spec.name, resource_id, audit_id)
    return {
        "undone": True,
        "audit_id": audit_id,
        "action": spec.name,
        # Named so the confirmation can say *what* was reversed. An undo the
        # operator cannot tie back to a resource is not a confirmation.
        "resource_id": resource_id,
    }
