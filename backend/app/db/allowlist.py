from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, String
from sqlalchemy.orm import Mapped

from app.db.base import Base

#: An exception for one named resource. The original and the default: absent a
#: ``match_type``, every row ever written before patterns existed is one of
#: these, and must keep behaving exactly as it did.
MATCH_RESOURCE = "resource"

#: An exception for a class of resource — one rule, one resource type, one
#: workspace. Broader by design, and therefore fenced: both selectors are
#: required and an expiry is compulsory.
MATCH_PATTERN = "pattern"

MATCH_TYPES = (MATCH_RESOURCE, MATCH_PATTERN)


class AllowlistModel(Base):
    """
    Database model for the Enforcement Sentinel Allowlist.
    This table stores exceptions for resources that would otherwise be flagged by governance policies.
    """
    __tablename__ = "allowlist"

    id: Mapped[str] = Column(String, primary_key=True, comment="Unique UUID for the allowlist record")
    # Null for pattern rows, which describe a class rather than a resource. The
    # column was NOT NULL when every exception named one resource.
    resource_id: Mapped[Optional[str]] = Column(String, nullable=True, index=True, comment="Databricks ID or path of the resource; null for pattern rows")
    resource_type: Mapped[str] = Column(String, nullable=False, index=True, comment="Enum: app, cluster, job, dashboard, etc.")
    workspace: Mapped[str] = Column(String, nullable=False, index=True, comment="The workspace ID or name where this resource lives")
    justification: Mapped[str] = Column(String, nullable=False, comment="Reason for the exception")
    status: Mapped[str] = Column(String, nullable=False, default="approved", index=True, comment="Status: pending, approved, rejected")
    # Defaulted rather than nullable so that a row written before patterns
    # existed, or by anything that does not know about them, is a resource
    # exception. The alternative — treating an absent match_type as a pattern —
    # would turn every legacy row into a class-wide waiver.
    match_type: Mapped[str] = Column(String, nullable=False, default=MATCH_RESOURCE, index=True, comment="resource (one named resource) or pattern (a class)")
    # Which rule a pattern waives, as its public ID, e.g. CST-CLU-005. Null for
    # resource rows, which waive every failing rule for that resource.
    rule_id: Mapped[Optional[str]] = Column(String, nullable=True, index=True, comment="Public rule ID a pattern exception waives")
    created_by: Mapped[Optional[str]] = Column(String, nullable=True, comment="Who asked for the exception")
    # Null means the exception never expires. Rego has to test for that
    # explicitly: `not exception.expires_at` does not match a JSON null, so an
    # expiry-less exception silently failed to apply before this was handled.
    #
    # Pattern rows are not allowed to be null — see the API. A permanent
    # class-wide waiver is a policy change that never went through a pull
    # request, which is the thing this system exists to prevent.
    expires_at: Mapped[Optional[datetime]] = Column(DateTime, nullable=True, comment="When the exception lapses; null never expires")
    created_at: Mapped[datetime] = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
