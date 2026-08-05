"""The audit row is written before the action, and undo round-trips.

Ordering is the point of the first half. A process killed mid-termination must
leave a record saying what was attempted; writing the row afterwards means the
actions that went most wrong are precisely the ones with no trace.

The second half proves that a Tier 2 action's captured state is enough to put
the resource back — which is the entire justification for Tier 2 being allowed
at all.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.actions import ActionTier
from app.core.enforcement import (
    ActionRequest,
    EnforcementApproval,
    ScanMode,
    resolve_effective_action,
)
from app.db.enforcement_audit import EnforcementAuditModel
from app.providers.databricks.handlers.base import (
    BaseResourceHandler,
    SupportsRevokeAccess,
)
from app.services.action_executor import (
    ActionExecutionError,
    execute_action,
    undo_action,
)

pytestmark = pytest.mark.safety

WORKSPACE = "prod-analytics"
RUN_ID = "run-audit-1"


class RecordingHandler(BaseResourceHandler, SupportsRevokeAccess):
    """A handler that records the order of events instead of calling an SDK.

    It inherits the mixin rather than merely defining the methods, because
    capability in this codebase is nominal: `supports()` does an `isinstance`
    check, so a fake that only quacks correctly would be refused — which is the
    behaviour under test elsewhere.
    """

    resource_type = "dashboard"

    def __init__(self, events, *, fail: bool = False):
        super().__init__(workspace_client=None)
        self.events = events
        self.fail = fail
        self.restored = None

    async def discover(self):
        return []

    async def revoke_access(self, resource_id, *, authorization=None):
        self.events.append(("revoke_access", resource_id))
        if self.fail:
            raise RuntimeError("the workspace said no")
        # The prior ACL, which is what makes this reversible.
        return {"prior_acl": [{"user_name": "someone@company.com", "level": "CAN_MANAGE"}]}

    async def restore_access(self, resource_id, undo_payload):
        self.events.append(("restore_access", resource_id))
        self.restored = undo_payload
        return True

    async def warn(self, resource_id, message, owner=None):
        self.events.append(("warn", resource_id))
        return True


@pytest.fixture
def remediate_authorization():
    return resolve_effective_action(
        ActionRequest(
            requested_action="REVOKE_ACCESS",
            resource_type="dashboard",
            resource_id="dash-1",
            workspace=WORKSPACE,
            mode=ScanMode.REMEDIATE,
            run_id=RUN_ID,
            supported_methods=frozenset({"revoke_access", "warn"}),
        )
    )


async def test_the_audit_row_exists_before_the_handler_runs(
    app_db, db_session, remediate_authorization
):
    """The intent row must be queryable from inside the handler."""
    assert remediate_authorization.action == "REVOKE_ACCESS"
    events: list = []

    seen_during_call = {}

    class ObservingHandler(RecordingHandler):
        async def revoke_access(self, resource_id, *, authorization=None):
            seen_during_call["rows"] = (
                db_session.query(EnforcementAuditModel)
                .filter(EnforcementAuditModel.resource_id == resource_id)
                .count()
            )
            return await super().revoke_access(resource_id, authorization=authorization)

    await execute_action(
        ObservingHandler(events),
        remediate_authorization,
        workspace=WORKSPACE,
        resource_id="dash-1",
        resource_type="dashboard",
        run_id=RUN_ID,
    )

    assert seen_during_call["rows"] == 1, (
        "No audit row existed while the action was running, so a crash mid-action "
        "would leave no trace of it."
    )


async def test_a_failed_action_still_leaves_an_audit_row(
    app_db, db_session, remediate_authorization
):
    result = await execute_action(
        RecordingHandler([], fail=True),
        remediate_authorization,
        workspace=WORKSPACE,
        resource_id="dash-1",
        resource_type="dashboard",
        run_id=RUN_ID,
    )

    assert result["executed"] is False
    row = db_session.query(EnforcementAuditModel).get(result["audit_id"])
    assert row.outcome == "failed"
    assert "the workspace said no" in (row.error or "")


async def test_a_restrict_action_refuses_to_run_without_an_audit_row(
    app_db, monkeypatch, remediate_authorization
):
    """No record, no action. Anything that changes a resource needs a trace."""
    from app.services import action_executor

    monkeypatch.setattr(action_executor, "record_intent", lambda *a, **k: None)

    with pytest.raises(ActionExecutionError, match="audit record could not be written"):
        await execute_action(
            RecordingHandler([]),
            remediate_authorization,
            workspace=WORKSPACE,
            resource_id="dash-1",
            resource_type="dashboard",
            run_id=RUN_ID,
        )


async def test_undo_restores_the_captured_state(
    app_db, db_session, remediate_authorization
):
    """The round trip: revoke, then put it back from what was captured."""
    handler = RecordingHandler([])

    result = await execute_action(
        handler,
        remediate_authorization,
        workspace=WORKSPACE,
        resource_id="dash-1",
        resource_type="dashboard",
        run_id=RUN_ID,
    )
    assert result["executed"] is True
    assert result["undo_payload"]["prior_acl"]

    await undo_action(result["audit_id"], handler, undone_by="operator@company.com")

    assert handler.restored == result["undo_payload"]
    assert [name for name, _ in handler.events] == ["revoke_access", "restore_access"]

    row = db_session.query(EnforcementAuditModel).get(result["audit_id"])
    assert row.undone_at is not None
    assert row.undone_by == "operator@company.com"


async def test_an_action_cannot_be_undone_twice(
    app_db, remediate_authorization
):
    handler = RecordingHandler([])
    result = await execute_action(
        handler,
        remediate_authorization,
        workspace=WORKSPACE,
        resource_id="dash-1",
        resource_type="dashboard",
        run_id=RUN_ID,
    )
    await undo_action(result["audit_id"], handler)

    with pytest.raises(ActionExecutionError, match="already undone"):
        await undo_action(result["audit_id"], handler)


async def test_destructive_actions_report_that_they_cannot_be_undone(
    app_db, db_session, monkeypatch
):
    """Tier 3 is irreversible by definition; the error says so rather than failing oddly."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENFORCEMENT_ENABLED", True, raising=False)
    monkeypatch.setattr(
        settings, "DESTRUCTIVE_ACTION_WORKSPACES", WORKSPACE, raising=False
    )

    authorization = resolve_effective_action(
        ActionRequest(
            requested_action="DELETE",
            resource_type="dashboard",
            resource_id="dash-2",
            workspace=WORKSPACE,
            mode=ScanMode.ENFORCE,
            run_id=RUN_ID,
            policy_declares_destructive=True,
            approval=EnforcementApproval(
                run_id=RUN_ID,
                approved_by="operator@company.com",
                workspace=WORKSPACE,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            ),
            supported_methods=frozenset({"delete"}),
        )
    )
    assert authorization.tier == ActionTier.DESTRUCTIVE

    row = EnforcementAuditModel(
        run_id=RUN_ID,
        workspace=WORKSPACE,
        resource_id="dash-2",
        resource_type="dashboard",
        requested_action="DELETE",
        effective_action="DELETE",
        tier=int(ActionTier.DESTRUCTIVE),
        mode="enforce",
        outcome="succeeded",
        started_at=datetime.utcnow(),
    )
    db_session.add(row)
    db_session.commit()

    with pytest.raises(ActionExecutionError, match="not reversible"):
        await undo_action(row.id, RecordingHandler([]))


async def test_execute_action_refuses_a_self_authorised_action(app_db):
    """The executor is the second place a forged authorisation is caught."""
    from app.core.enforcement import EffectiveAction

    forged = EffectiveAction(
        requested_action="REVOKE_ACCESS",
        action="REVOKE_ACCESS",
        tier=ActionTier.RESTRICT,
        requested_tier=ActionTier.RESTRICT,
        mode=ScanMode.REMEDIATE,
    )

    with pytest.raises(ActionExecutionError, match="cannot be self-authorised"):
        await execute_action(
            RecordingHandler([]),
            forged,
            workspace=WORKSPACE,
            resource_id="dash-1",
            resource_type="dashboard",
        )
