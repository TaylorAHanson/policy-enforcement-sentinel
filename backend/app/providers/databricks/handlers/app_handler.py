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

    discovered_fields = {
        "id": "The app name, which is also its identifier.",
        "name": "The app name.",
        "type": 'Always "app".',
        "owner": "The email of whoever created the app.",
        "state": "Deployment state of the active deployment, or UNKNOWN if it has never deployed.",
        "url": "The app's URL, or null.",
        "shared_with": (
            'Group names with access. Contains "ALL_USERS" when shared with '
            "everybody. Empty when the ACL could not be read."
        ),
        "tags": "Always empty. The Apps API exposes no tags, so a tagging rule cannot be written for apps.",
    }

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
                    "shared_with": await self._shared_with(app.name),
                    "tags": {},
                }
            )
        return resources

    async def _shared_with(self, name: str) -> List[str]:
        """Groups with access. Guarded: one unreadable ACL is not a failed scan."""
        try:
            return await asyncio.to_thread(
                permissions.shared_with, self.workspace_client, "app", name
            )
        except Exception as e:
            logger.debug("Could not read the ACL for app %s: %s", name, e)
            return []

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
