import uuid
from datetime import datetime

from app.db.sentinel_finding import SentinelFindingModel
from app.db.sentinel_run import SentinelRunModel


class SentinelRunFactory:
    """A completed audit run. The safe default, matching what ships."""

    @classmethod
    def build(cls, **overrides) -> SentinelRunModel:
        defaults = {
            "id": str(uuid.uuid4()),
            "workspace": "prod-analytics",
            "environment": "prod",
            "mode": "audit",
            "status": "completed",
            "started_at": datetime.utcnow(),
            "completed_at": datetime.utcnow(),
            "total_resources": 10,
            "violation_count": 2,
            "check_count": 8,
            "remediated_count": 0,
            "downgraded_count": 0,
            "results": {"workspaces": {"prod-analytics": "completed"}},
        }
        defaults.update(overrides)
        return SentinelRunModel(**defaults)

    @classmethod
    def create(cls, session, **overrides) -> SentinelRunModel:
        row = cls.build(**overrides)
        session.add(row)
        session.commit()
        return row


class SentinelFindingFactory:
    """A violation that requested WARN and got it."""

    _counter = 0

    @classmethod
    def build(cls, run_id: str, **overrides) -> SentinelFindingModel:
        cls._counter += 1
        n = cls._counter
        defaults = {
            "run_id": run_id,
            "kind": "violation",
            "workspace": "prod-analytics",
            "environment": "prod",
            "resource_id": f"cluster-{n}",
            "resource_type": "cluster",
            "resource_name": f"analytics-{n}",
            "owner": "owner@company.com",
            "policy": "clusters",
            "rule_id": "missing_cost_tags",
            "policy_id": "CST-CLU-003",
            "category": "cost",
            "severity": "MEDIUM",
            "message": "Missing the 'cost-center' tag.",
            "requested_action": "WARN",
            "effective_action": "WARN",
            "tier": 1,
            "requested_tier": 1,
            "executed": False,
        }
        defaults.update(overrides)
        valid = {c.name for c in SentinelFindingModel.__table__.columns}
        return SentinelFindingModel(**{k: v for k, v in defaults.items() if k in valid})

    @classmethod
    def create(cls, session, run_id: str, **overrides) -> SentinelFindingModel:
        row = cls.build(run_id, **overrides)
        session.add(row)
        session.commit()
        session.refresh(row)
        return row

    @classmethod
    def create_many(cls, session, run_id: str, count: int, **overrides):
        """Bulk rows in one commit.

        Tests that care about paging and truncation need hundreds of findings,
        and a commit per row makes those tests slow enough that people stop
        writing them.
        """
        rows = [cls.build(run_id, **overrides) for _ in range(count)]
        session.add_all(rows)
        session.commit()
        return rows

    @classmethod
    def downgraded(cls, session, run_id: str, **overrides) -> SentinelFindingModel:
        """A finding where a gate refused the action the policy asked for."""
        overrides.setdefault("requested_action", "DELETE")
        overrides.setdefault("requested_tier", 3)
        overrides.setdefault("effective_action", "WARN")
        overrides.setdefault("tier", 1)
        overrides.setdefault(
            "downgrade_reason", "ENFORCEMENT_ENABLED must be on. It ships off."
        )
        return cls.create(session, run_id, **overrides)

    @classmethod
    def passing_check(cls, session, run_id: str, **overrides) -> SentinelFindingModel:
        """A rule that ran and found nothing wrong.

        Recorded so "no findings" can be told apart from "never evaluated".
        """
        overrides.setdefault("kind", "check")
        overrides.setdefault("severity", None)
        overrides.setdefault("message", "Compliant.")
        return cls.create(session, run_id, **overrides)
