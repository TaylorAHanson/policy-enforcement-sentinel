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

    discovered_fields = {
        "id": "The endpoint name.",
        "name": "The endpoint name.",
        "type": 'Always "model_serving_endpoint".',
        "owner": "The email of whoever created the endpoint.",
        "endpoint_type": "FOUNDATION_MODEL_API, EXTERNAL_MODEL, and so on.",
        "ready": "Readiness state as a string. May be empty when unknown.",
        "scale_to_zero": (
            "Whether every served model scales to zero. True when the endpoint "
            "serves no models of its own, such as a foundation model endpoint, "
            "because there is no always-on capacity to bill for."
        ),
        "inference_logging": (
            "Whether inference is captured to a Unity Catalog table."
        ),
        "shared_with": (
            'Group names with access. Contains "ALL_USERS" when shared with '
            "everybody. Empty when the ACL could not be read."
        ),
        "tags": "Endpoint tags as a string map.",
    }

    async def discover(self) -> List[Dict[str, Any]]:
        resources = []
        for endpoint in self.workspace_client.serving_endpoints.list():
            tags = {}
            for tag in getattr(endpoint, "tags", None) or []:
                if hasattr(tag, "key"):
                    tags[tag.key] = getattr(tag, "value", "")

            state = getattr(endpoint, "state", None)
            config = getattr(endpoint, "config", None)

            # `all` over an empty list is True, which is the answer we want: an
            # endpoint serving no models of its own holds no warm capacity, so
            # there is nothing for a scale-to-zero rule to complain about.
            served = list(getattr(config, "served_models", None) or []) if config else []
            scale_to_zero = all(
                bool(getattr(model, "scale_to_zero_enabled", False)) for model in served
            )

            capture = getattr(config, "auto_capture_config", None) if config else None
            inference_logging = bool(getattr(capture, "enabled", False)) if capture else False

            resources.append(
                {
                    "id": endpoint.name,
                    "name": endpoint.name,
                    "type": "model_serving_endpoint",
                    "owner": getattr(endpoint, "creator", "unknown"),
                    "endpoint_type": str(getattr(endpoint, "endpoint_type", "") or "unknown"),
                    "ready": str(getattr(state, "ready", "") or "") if state else "",
                    "scale_to_zero": scale_to_zero,
                    "inference_logging": inference_logging,
                    "shared_with": await self._shared_with(endpoint.name),
                    "tags": tags,
                }
            )
        return resources

    async def _shared_with(self, name: str) -> List[str]:
        """Groups with access. Guarded: one unreadable ACL is not a failed scan.

        An empty list therefore means either "shared with nobody" or "could not
        tell", which the sharing rule has to treat as not-a-violation — the
        alternative is flagging every endpoint whenever the scanner lacks
        CAN_MANAGE.
        """
        try:
            return await asyncio.to_thread(
                permissions.shared_with,
                self.workspace_client,
                "model_serving_endpoint",
                name,
            )
        except Exception as e:
            logger.debug("Could not read the ACL for serving endpoint %s: %s", name, e)
            return []

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
