import uuid
from datetime import datetime, timedelta

from app.db.allowlist import AllowlistModel


class AllowlistFactory:
    """Allowlist entries, defaulting to an active exception on a cluster."""

    _counter = 0

    @classmethod
    def build(cls, **overrides) -> AllowlistModel:
        cls._counter += 1
        defaults = {
            # The primary key is a UUID string the application generates, not a
            # sequence, so it has to be supplied here.
            "id": str(uuid.uuid4()),
            "resource_id": f"cluster-{cls._counter}",
            "resource_type": "cluster",
            "workspace": "prod-analytics",
            "justification": "Approved exception for the migration window.",
            "status": "approved",
            "expires_at": datetime.utcnow() + timedelta(days=30),
        }
        defaults.update(overrides)
        # Tolerate columns that a given schema version does not have, so a
        # factory stays usable through a migration.
        valid = {c.name for c in AllowlistModel.__table__.columns}
        return AllowlistModel(**{k: v for k, v in defaults.items() if k in valid})

    @classmethod
    def create(cls, session, **overrides) -> AllowlistModel:
        row = cls.build(**overrides)
        session.add(row)
        session.commit()
        session.refresh(row)
        return row

    @classmethod
    def expired(cls, session, **overrides) -> AllowlistModel:
        """An exception that has lapsed. Policies must stop honouring it."""
        overrides.setdefault("expires_at", datetime.utcnow() - timedelta(days=1))
        return cls.create(session, **overrides)
