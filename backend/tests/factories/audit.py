from datetime import datetime

from app.db.enforcement_audit import EnforcementAuditModel


class EnforcementAuditFactory:
    """A succeeded, reversible Tier 2 action."""

    _counter = 0

    @classmethod
    def build(cls, **overrides) -> EnforcementAuditModel:
        cls._counter += 1
        defaults = {
            "run_id": "run-1",
            "workspace": "prod-analytics",
            "resource_id": f"dash-{cls._counter}",
            "resource_type": "dashboard",
            "policy": "dashboards",
            "policy_id": "SEC-DSH-001",
            "requested_action": "REVOKE_ACCESS",
            "effective_action": "REVOKE_ACCESS",
            "tier": 2,
            "mode": "remediate",
            "outcome": "succeeded",
            "undo_payload": {"prior_acl": [{"user_name": "a@b.com", "level": "CAN_VIEW"}]},
            "started_at": datetime.utcnow(),
            "completed_at": datetime.utcnow(),
        }
        defaults.update(overrides)
        return EnforcementAuditModel(**defaults)

    @classmethod
    def create(cls, session, **overrides) -> EnforcementAuditModel:
        row = cls.build(**overrides)
        session.add(row)
        session.commit()
        session.refresh(row)
        return row

    @classmethod
    def intent_only(cls, session, **overrides) -> EnforcementAuditModel:
        """The row as it exists while the action is still running."""
        overrides.setdefault("outcome", "intent")
        overrides.setdefault("undo_payload", None)
        overrides.setdefault("completed_at", None)
        return cls.create(session, **overrides)
