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

    discovered_fields = {
        "id": "The instance name.",
        "name": "The instance name.",
        "type": 'Always "lakebase_instance".',
        "owner": "The email of whoever created the instance.",
        "state": "AVAILABLE, STOPPED, and so on.",
        "capacity": "The capacity tier as a string. May be empty.",
        "capacity_units": (
            "Provisioned node count, or null when the API did not report one. "
            "This is what is billed for; it says nothing about what is used."
        ),
        "stopped": "Whether the instance is stopped.",
        "retention_window_days": "Backup retention in days, or null.",
        "tags": "Custom tags as a string map.",
    }

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
                    # The `effective_` variants fold in whatever the parent
                    # instance or a policy imposes, so they describe what is
                    # actually running. The plain fields only describe what was
                    # asked for, which is not what gets billed.
                    "capacity": str(
                        getattr(instance, "effective_capacity", None)
                        or getattr(instance, "capacity", "")
                        or ""
                    ),
                    "capacity_units": (
                        getattr(instance, "effective_node_count", None)
                        if getattr(instance, "effective_node_count", None) is not None
                        else getattr(instance, "node_count", None)
                    ),
                    "stopped": state.upper() == "STOPPED",
                    "retention_window_days": (
                        getattr(instance, "effective_retention_window_in_days", None)
                        if getattr(instance, "effective_retention_window_in_days", None)
                        is not None
                        else getattr(instance, "retention_window_in_days", None)
                    ),
                    "tags": dict(
                        getattr(instance, "effective_custom_tags", None)
                        or getattr(instance, "custom_tags", None)
                        or {}
                    ),
                }
            )
        return resources
