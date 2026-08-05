from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Integer, String

from app.db.base import Base


class SentinelRunModel(Base):
    """One execution of the Sentinel across one or more workspaces.

    ``results`` holds only a **summary** — counts, per-workspace status, the
    remediation tally. The individual findings live in ``sentinel_findings``,
    one row each. Previously the entire scan output was serialised into this
    JSON column, which meant listing runs pulled megabytes per row and the
    dashboard had no way to filter or paginate without loading everything.
    """

    __tablename__ = "sentinel_runs"

    id = Column(String, primary_key=True, comment="Unique UUID for the run")
    workspace = Column(String, nullable=False, comment="Comma separated workspaces scanned")
    environment = Column(String, nullable=False, comment="Environment string")
    mode = Column(String, nullable=False, comment="audit, remediate, or enforce")
    status = Column(
        String,
        nullable=False,
        default="running",
        index=True,
        comment="running, completed, failed, partial",
    )
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    completed_at = Column(DateTime, nullable=True)
    error = Column(String, nullable=True)

    # Denormalised counters so the run list renders without touching findings.
    total_resources = Column(Integer, nullable=False, default=0)
    violation_count = Column(Integer, nullable=False, default=0)
    check_count = Column(Integer, nullable=False, default=0)
    remediated_count = Column(Integer, nullable=False, default=0)
    # How many findings asked for more than they got. A non-zero value here is
    # the signal that the run's behaviour differed from what the policies asked
    # for, which is the thing an operator most needs to notice.
    downgraded_count = Column(Integer, nullable=False, default=0)

    results = Column(JSON, nullable=True, comment="Summary object: counts and per-workspace status")

    #: Who confirmed this run may act destructively, if anyone.
    approved_by = Column(String, nullable=True)
    approval_id = Column(String, nullable=True)
