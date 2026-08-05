import logging
from typing import Any, Dict, List

from app.providers.databricks.handlers.base import BaseResourceHandler

logger = logging.getLogger(__name__)


class LakebaseResourceHandler(BaseResourceHandler):
    """Lakebase (managed Postgres) database instances.

    Discovery and warning only. A database instance holds the only copy of
    whatever is in it, so no destructive capability is offered, and instance
    permissions are managed through catalog grants rather than on the instance —
    so this handler deliberately claims no ``revoke_access`` either. Claiming a
    capability it cannot honour would let the chokepoint downgrade into a method
    that throws, which is worse than having no capability at all.
    """

    resource_type = "lakebase_instance"

    async def discover(self) -> List[Dict[str, Any]]:
        resources: List[Dict[str, Any]] = []
        database = getattr(self.workspace_client, "database", None)
        if database is None:
            logger.debug("SDK has no database API; skipping Lakebase discovery.")
            return resources

        for instance in database.list_database_instances():
            state = str(getattr(instance, "state", "") or "UNKNOWN")
            resources.append(
                {
                    "id": getattr(instance, "name", None),
                    "name": getattr(instance, "name", None),
                    "type": "lakebase_instance",
                    "owner": getattr(instance, "creator", "unknown"),
                    "state": state,
                    "capacity": str(getattr(instance, "capacity", "") or ""),
                    "stopped": state.upper() == "STOPPED",
                    "retention_window_days": getattr(instance, "retention_window_in_days", None),
                    "tags": {},
                }
            )
        return resources
