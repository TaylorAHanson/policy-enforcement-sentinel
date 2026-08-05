import asyncio
import logging
from typing import Any, Dict, List

from app.providers.databricks import destructive, permissions
from app.providers.databricks.handlers.base import (
    BaseResourceHandler,
    SupportsDelete,
    SupportsRevokeAccess,
)

logger = logging.getLogger(__name__)


class AppResourceHandler(BaseResourceHandler, SupportsRevokeAccess, SupportsDelete):
    """Databricks Apps."""

    resource_type = "app"

    async def discover(self) -> List[Dict[str, Any]]:
        resources = []
        for app in self.workspace_client.apps.list():
            deployment = getattr(app, "active_deployment", None)
            resources.append(
                {
                    "id": app.name,
                    "name": app.name,
                    "type": "app",
                    "owner": getattr(app, "creator", "unknown"),
                    "state": str(getattr(deployment, "state", "UNKNOWN"))
                    if deployment
                    else "UNKNOWN",
                    "url": getattr(app, "url", None),
                    "tags": {},
                }
            )
        return resources

    async def revoke_access(self, resource_id: str, *, authorization=None) -> Dict[str, Any]:
        return await asyncio.to_thread(
            permissions.revoke_permissions, self.workspace_client, "app", resource_id
        )

    async def restore_access(self, resource_id: str, undo_payload: Dict[str, Any]) -> bool:
        return await asyncio.to_thread(
            permissions.restore_permissions, self.workspace_client, undo_payload
        )

    async def delete(self, resource_id: str, *, authorization) -> bool:
        return await asyncio.to_thread(
            destructive.delete_app,
            self.workspace_client,
            resource_id,
            authorization=authorization,
        )
