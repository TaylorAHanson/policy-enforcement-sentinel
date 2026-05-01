from datetime import datetime
from sqlalchemy import Column, String, DateTime, JSON
from app.db.base import Base

class SentinelRunModel(Base):
    """
    Database model for the Enforcement Sentinel Runs.
    Stores the history of automated and manual policy evaluations.
    """
    __tablename__ = "sentinel_runs"
    
    id = Column(String, primary_key=True, comment="Unique UUID for the run")
    workspace = Column(String, nullable=False, comment="Comma separated workspaces scanned")
    environment = Column(String, nullable=False, comment="Environment string")
    mode = Column(String, nullable=False, comment="audit or enforce mode")
    status = Column(String, nullable=False, default="running", index=True, comment="running, completed, failed")
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    error = Column(String, nullable=True)
    results = Column(JSON, nullable=True, comment="Detailed JSON results of the scan")
