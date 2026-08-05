from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Index, Integer, String, Text

from app.db.base import Base


class EnforcementAuditModel(Base):
    """The record of something the Sentinel did, or tried to do, to a resource.

    The row is written **before** the handler is invoked, carrying the intent,
    and updated afterwards with the outcome. That ordering is deliberate: if the
    process dies mid-action, the intent row survives and someone can work out
    what was in flight. Writing the row after the fact would mean the only
    actions with no record are the ones that went most wrong.

    ``undo_payload`` holds the prior state for every Tier 2 action, which is
    what makes the undo endpoint possible.
    """

    __tablename__ = "enforcement_audit"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, nullable=True, index=True)

    workspace = Column(String, nullable=False, index=True)
    resource_id = Column(String, nullable=False)
    resource_type = Column(String, nullable=False)
    policy = Column(String, nullable=True)
    policy_id = Column(String, nullable=True)

    requested_action = Column(String, nullable=True)
    effective_action = Column(String, nullable=False)
    tier = Column(Integer, nullable=False, default=0)
    downgrade_reason = Column(Text, nullable=True)
    mode = Column(String, nullable=True)

    #: intent -> succeeded | failed | skipped
    outcome = Column(String, nullable=False, default="intent", index=True)
    error = Column(Text, nullable=True)

    #: Prior state, sufficient to reverse the action. Required for Tier 2.
    undo_payload = Column(JSON, nullable=True)
    undone_at = Column(DateTime, nullable=True)
    undone_by = Column(String, nullable=True)

    approved_by = Column(String, nullable=True)
    approval_id = Column(String, nullable=True)

    started_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_audit_run_outcome", "run_id", "outcome"),
        Index("ix_audit_resource", "workspace", "resource_id"),
    )

    @property
    def is_undoable(self) -> bool:
        return bool(self.undo_payload) and self.undone_at is None and self.outcome == "succeeded"
