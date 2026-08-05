"""Database package.

Importing this package registers every model on ``Base.metadata``. Anything that
calls ``Base.metadata.create_all`` (app startup, the test harness) must import
``app.db`` first, or it will silently create only the subset of tables that
happen to have been imported already.
"""
from app.db.base import Base  # noqa: F401
from app.db.allowlist import AllowlistModel  # noqa: F401
from app.db.app_setting import AppSettingModel  # noqa: F401
from app.db.enforcement_audit import EnforcementAuditModel  # noqa: F401
from app.db.sentinel_finding import SentinelFindingModel  # noqa: F401
from app.db.sentinel_run import SentinelRunModel  # noqa: F401

__all__ = [
    "Base",
    "AllowlistModel",
    "AppSettingModel",
    "EnforcementAuditModel",
    "SentinelFindingModel",
    "SentinelRunModel",
]
