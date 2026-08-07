from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
)

from app.db.base import Base

#: A finding that is currently true of the estate.
STATUS_OPEN = "open"
#: A finding that was true and, on positive evidence, no longer is.
STATUS_RESOLVED = "resolved"

#: The rule was evaluated against the resource and passed. The only reason that
#: means somebody fixed something.
RESOLUTION_FIXED = "fixed"
#: The resource was not in a successful enumeration of its type. The finding is
#: no longer true because the thing it was about is gone, which is a different
#: fact from the problem having been addressed — a deleted production cluster
#: closes its findings without anybody having improved anything.
RESOLUTION_RESOURCE_GONE = "resource_gone"
#: The resource is still there and the rule produced no verdict about it. A
#: policy was narrowed, retired, or its scope changed. Nothing about the estate
#: improved; we simply stopped asking, and saying "fixed" here would turn an
#: edit to a policy file into a wave of good news.
RESOLUTION_NOT_EVALUATED = "not_evaluated"


class SentinelFindingStateModel(Base):
    """One finding, across every scan that has ever seen it.

    ``sentinel_findings`` is a log: every scan appends a row per resource per
    rule, and after five scans of one estate it held 39,264 rows describing
    about 3,800 facts. Nothing in it can answer the question an operator
    actually has, which is not "what is wrong" — that number is four digits and
    has not moved in weeks — but "what changed, and what has been ignored the
    longest".

    This table is that question's shape: one row per finding rather than per
    sighting, carrying when it first appeared, when it was last confirmed, and
    what happened to it. The log stays as the evidence trail; this is the index
    into it.

    The care is all in closing one. A finding vanishing from a scan is not proof
    it was fixed — the resource may be deleted, a policy may have been narrowed,
    or discovery may simply have failed to enumerate that type. If a permissions
    change breaks the volume handler and four hundred findings quietly resolve,
    the app reports a triumph and the estate is exactly as it was. So nothing
    closes without evidence, and the three ways one can close are recorded
    separately, because only one of them is good news.
    """

    __tablename__ = "sentinel_finding_state"

    #: workspace + resource type + resource id + policy id, hashed. Resource ids
    #: are unique within a type and not across one — a real estate had
    #: `regression-validation-dev` as both an app and a Lakebase instance — so
    #: the type is part of the identity rather than a detail hanging off it.
    fingerprint = Column(String, primary_key=True)

    workspace = Column(String, nullable=False, index=True)
    environment = Column(String, nullable=True)

    resource_id = Column(String, nullable=True)
    resource_type = Column(String, nullable=True, index=True)
    resource_name = Column(String, nullable=True)
    owner = Column(String, nullable=True, index=True)

    policy = Column(String, nullable=True, index=True)
    rule_id = Column(String, nullable=True)
    policy_id = Column(String, nullable=True, index=True)
    category = Column(String, nullable=True, index=True)
    severity = Column(String, nullable=True, index=True)
    message = Column(Text, nullable=True)

    status = Column(String, nullable=False, default=STATUS_OPEN, index=True)
    #: Why it closed. Null while open. See the RESOLUTION_* constants.
    resolution = Column(String, nullable=True, index=True)

    first_seen_at = Column(DateTime, nullable=True, index=True)
    first_seen_run = Column(String, nullable=True)

    #: The last scan that found this to be true. Not the last scan that ran.
    last_seen_at = Column(DateTime, nullable=True, index=True)
    last_seen_run = Column(String, nullable=True)

    #: The last scan that was in a position to judge it at all — which is a
    #: different thing, and the difference is what makes a stale finding
    #: visible. A finding whose resource type has failed to enumerate for three
    #: scans is not open-and-confirmed; it is open-and-unknown, and an interface
    #: that cannot tell those apart is quietly reporting stale data as current.
    last_evaluated_at = Column(DateTime, nullable=True, index=True)
    last_evaluated_run = Column(String, nullable=True)

    resolved_at = Column(DateTime, nullable=True, index=True)
    resolved_run = Column(String, nullable=True)

    #: How many scans have found it true. A proxy for how long it has been
    #: ignored that survives gaps in the scan schedule better than a date does.
    occurrences = Column(Integer, nullable=False, default=0)

    #: How many times it has closed and come back. Whack-a-mole: a resource
    #: repeatedly fixed and re-broken is a process problem, and it looks
    #: identical to a stable violation if you only count occurrences.
    reopened = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_state_status_severity", "status", "severity"),
        Index("ix_state_status_first_seen", "status", "first_seen_at"),
        Index("ix_state_workspace_status", "workspace", "status"),
    )


__all__ = [
    "RESOLUTION_FIXED",
    "RESOLUTION_NOT_EVALUATED",
    "RESOLUTION_RESOURCE_GONE",
    "STATUS_OPEN",
    "STATUS_RESOLVED",
    "SentinelFindingStateModel",
]
