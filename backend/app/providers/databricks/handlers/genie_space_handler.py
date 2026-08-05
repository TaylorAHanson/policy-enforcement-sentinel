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
                    "tags": {t.key: t.value for t in tags if hasattr(t, "key")},
                }
            )
        return resources

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
