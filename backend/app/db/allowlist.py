from datetime import datetime
from typing import Optional
from sqlalchemy import Column, String, DateTime
from sqlalchemy.orm import Mapped

from app.db.base import Base

class AllowlistModel(Base):
    """
    Database model for the Enforcement Sentinel Allowlist.
    This table stores exceptions for resources that would otherwise be flagged by governance policies.
    """
    __tablename__ = "allowlist"
    
    id: Mapped[str] = Column(String, primary_key=True, comment="Unique UUID for the allowlist record")
    resource_id: Mapped[str] = Column(String, nullable=False, index=True, comment="Databricks ID or path of the resource")
    resource_type: Mapped[str] = Column(String, nullable=False, index=True, comment="Enum: app, cluster, job, dashboard, etc.")
    workspace: Mapped[str] = Column(String, nullable=False, index=True, comment="The workspace ID or name where this resource lives")
    justification: Mapped[str] = Column(String, nullable=False, comment="Reason for the exception")
    status: Mapped[str] = Column(String, nullable=False, default="approved", index=True, comment="Status: pending, approved, rejected")
    created_at: Mapped[datetime] = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
