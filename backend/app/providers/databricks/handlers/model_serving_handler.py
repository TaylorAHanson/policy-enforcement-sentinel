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


class ModelServingEndpointResourceHandler(
    BaseResourceHandler, SupportsRevokeAccess, SupportsDelete
):
    """Model serving endpoints.

    Kept in this repo even though the sibling platform dropped it — serving
    endpoints are a meaningful cost and access surface.
    """

    resource_type = "model_serving_endpoint"

    async def discover(self) -> List[Dict[str, Any]]:
        resources = []
        for endpoint in self.workspace_client.serving_endpoints.list():
            tags = {}
            for tag in getattr(endpoint, "tags", None) or []:
                if hasattr(tag, "key"):
                    tags[tag.key] = getattr(tag, "value", "")

            state = getattr(endpoint, "state", None)
            resources.append(
                {
                    "id": endpoint.name,
                    "name": endpoint.name,
                    "type": "model_serving_endpoint",
                    "owner": getattr(endpoint, "creator", "unknown"),
                    "endpoint_type": str(getattr(endpoint, "endpoint_type", "") or "unknown"),
                    "ready": str(getattr(state, "ready", "") or "") if state else "",
                    "tags": tags,
                }
            )
        return resources

    async def revoke_access(self, resource_id: str, *, authorization=None) -> Dict[str, Any]:
        return await asyncio.to_thread(
            permissions.revoke_permissions,
            self.workspace_client,
            "model_serving_endpoint",
            resource_id,
        )

    async def restore_access(self, resource_id: str, undo_payload: Dict[str, Any]) -> bool:
        return await asyncio.to_thread(
            permissions.restore_permissions, self.workspace_client, undo_payload
        )

    async def delete(self, resource_id: str, *, authorization) -> bool:
        return await asyncio.to_thread(
            destructive.delete_serving_endpoint,
            self.workspace_client,
            resource_id,
            authorization=authorization,
        )
