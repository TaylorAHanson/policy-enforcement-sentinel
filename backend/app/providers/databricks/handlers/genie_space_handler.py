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


class GenieSpaceResourceHandler(BaseResourceHandler, SupportsRevokeAccess, SupportsDelete):
    """Genie spaces."""

    resource_type = "genie_space"

    discovered_fields = {
        "id": "The Genie space ID.",
        "name": "The space name.",
        "type": 'Always "genie_space".',
        "owner": "The email of whoever created the space.",
        "description": "The space description, or null.",
        "shared_with": (
            'Group names with access. Contains "ALL_USERS" when shared with '
            "everybody. Empty when the ACL could not be read."
        ),
        "tags": "Tags as a string map.",
    }

    async def discover(self) -> List[Dict[str, Any]]:
        resources = []
        response = self.workspace_client.genie.list_spaces()
        for space in getattr(response, "spaces", None) or []:
            tags = getattr(space, "tags", None) or []
            resources.append(
                {
                    "id": space.id,
                    "name": space.name,
                    "type": "genie_space",
                    "owner": getattr(space, "creator", "unknown"),
                    "description": getattr(space, "description", None),
                    "shared_with": await self._shared_with(space.id),
                    "tags": {t.key: t.value for t in tags if hasattr(t, "key")},
                }
            )
        return resources

    async def _shared_with(self, space_id: str) -> List[str]:
        """Groups with access. Guarded: one unreadable ACL is not a failed scan."""
        try:
            return await asyncio.to_thread(
                permissions.shared_with, self.workspace_client, "genie_space", space_id
            )
        except Exception as e:
            logger.debug("Could not read the ACL for Genie space %s: %s", space_id, e)
            return []

    async def revoke_access(self, resource_id: str, *, authorization=None) -> Dict[str, Any]:
        return await asyncio.to_thread(
            permissions.revoke_permissions, self.workspace_client, "genie_space", resource_id
        )

    async def restore_access(self, resource_id: str, undo_payload: Dict[str, Any]) -> bool:
        return await asyncio.to_thread(
            permissions.restore_permissions, self.workspace_client, undo_payload
        )

    async def delete(self, resource_id: str, *, authorization) -> bool:
        return await asyncio.to_thread(
            destructive.trash_genie_space,
            self.workspace_client,
            resource_id,
            authorization=authorization,
        )
