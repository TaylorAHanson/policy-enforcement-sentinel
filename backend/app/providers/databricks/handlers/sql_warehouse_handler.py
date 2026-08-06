import asyncio
import logging
from typing import Any, Dict, List

from app.providers.databricks import destructive, permissions
from app.providers.databricks.handlers.base import (
    BaseResourceHandler,
    SupportsDelete,
    SupportsRevokeAccess,
    SupportsThrottle,
)

logger = logging.getLogger(__name__)


class SqlWarehouseResourceHandler(
    BaseResourceHandler, SupportsRevokeAccess, SupportsThrottle, SupportsDelete
):
    """SQL warehouses. Throttling the cluster size caps spend without downtime."""

    resource_type = "sql_warehouse"

    discovered_fields = {
        "id": "The warehouse ID.",
        "name": "The warehouse name.",
        "type": 'Always "sql_warehouse".',
        "owner": "The email of whoever created the warehouse.",
        "state": "RUNNING, STOPPED, STARTING and so on.",
        "auto_stop_mins": "Idle minutes before auto-stop, or null when it is disabled.",
        "max_num_clusters": "Upper bound of the scaling range, or null.",
        "warehouse_type": "PRO, CLASSIC, and so on. May be an empty string.",
        "serverless": "Whether serverless compute is enabled.",
        "tags": "Custom tags as a string map.",
    }

    async def discover(self) -> List[Dict[str, Any]]:
        resources = []
        for warehouse in self.workspace_client.warehouses.list():
            tags_obj = getattr(warehouse, "tags", None)
            custom_tags = getattr(tags_obj, "custom_tags", None) or [] if tags_obj else []
            state = getattr(warehouse, "state", None)
            resources.append(
                {
                    "id": warehouse.id,
                    "name": warehouse.name,
                    "type": "sql_warehouse",
                    "owner": getattr(warehouse, "creator_name", "unknown"),
                    "state": getattr(state, "value", str(state)) if state else "UNKNOWN",
                    "auto_stop_mins": getattr(warehouse, "auto_stop_mins", None),
                    "max_num_clusters": getattr(warehouse, "max_num_clusters", None),
                    "warehouse_type": str(getattr(warehouse, "warehouse_type", "") or ""),
                    "serverless": bool(
                        getattr(warehouse, "enable_serverless_compute", False)
                    ),
                    "tags": {t.key: t.value for t in custom_tags},
                }
            )
        return resources

    # --- Tier 2 -----------------------------------------------------------

    async def revoke_access(self, resource_id: str, *, authorization=None) -> Dict[str, Any]:
        return await asyncio.to_thread(
            permissions.revoke_permissions,
            self.workspace_client,
            "sql_warehouse",
            resource_id,
        )

    async def restore_access(self, resource_id: str, undo_payload: Dict[str, Any]) -> bool:
        return await asyncio.to_thread(
            permissions.restore_permissions, self.workspace_client, undo_payload
        )

    async def throttle(self, resource_id: str, *, authorization=None) -> Dict[str, Any]:
        current = await asyncio.to_thread(self.workspace_client.warehouses.get, id=resource_id)
        undo_payload = {
            "resource_id": resource_id,
            "max_num_clusters": getattr(current, "max_num_clusters", None),
            "auto_stop_mins": getattr(current, "auto_stop_mins", None),
        }

        await asyncio.to_thread(
            self.workspace_client.warehouses.edit,
            id=resource_id,
            name=current.name,
            cluster_size=current.cluster_size,
            max_num_clusters=1,
            auto_stop_mins=10,
        )
        logger.info(
            "Throttled warehouse %s: max clusters 1, auto-stop 10 minutes.", resource_id
        )
        return undo_payload

    async def unthrottle(self, resource_id: str, undo_payload: Dict[str, Any]) -> bool:
        current = await asyncio.to_thread(self.workspace_client.warehouses.get, id=resource_id)
        await asyncio.to_thread(
            self.workspace_client.warehouses.edit,
            id=resource_id,
            name=current.name,
            cluster_size=current.cluster_size,
            max_num_clusters=undo_payload.get("max_num_clusters"),
            auto_stop_mins=undo_payload.get("auto_stop_mins"),
        )
        return True

    # --- Tier 3 -----------------------------------------------------------

    async def delete(self, resource_id: str, *, authorization) -> bool:
        return await asyncio.to_thread(
            destructive.delete_warehouse,
            self.workspace_client,
            resource_id,
            authorization=authorization,
        )
