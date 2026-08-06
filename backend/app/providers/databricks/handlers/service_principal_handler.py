import asyncio
import logging
from typing import Any, Dict, List

from app.providers.databricks import destructive
from app.providers.databricks.handlers.base import (
    BaseResourceHandler,
    SupportsDelete,
    SupportsDisable,
)

logger = logging.getLogger(__name__)


class ServicePrincipalResourceHandler(BaseResourceHandler, SupportsDisable, SupportsDelete):
    """Service principals.

    Deactivating is the right response to a stale or non-compliant service
    principal: it stops the credential working immediately and is a single
    field flip to undo. Deleting loses the identity and every grant attached to
    it, and is not recoverable.
    """

    resource_type = "service_principal"

    discovered_fields = {
        "id": "The SCIM ID.",
        "name": "The display name, or null.",
        "type": 'Always "service_principal".',
        "owner": "The display name again. A service principal has no separate owner.",
        "active": "Whether the principal is enabled.",
        "application_id": "The application ID, or null.",
        "entitlements": (
            "SCIM entitlement values, such as allow-cluster-create or "
            "databricks-sql-access. What the principal may do in this workspace."
        ),
        "roles": (
            "SCIM role values. This is where account_admin appears, and it is "
            "populated only when the client is bound to the account rather than "
            "a single workspace — expect it to be empty on a workspace client."
        ),
        "tags": "Always empty. SCIM exposes no tags.",
    }

    async def discover(self) -> List[Dict[str, Any]]:
        resources = []
        for sp in self.workspace_client.service_principals.list():
            resources.append(
                {
                    "id": sp.id,
                    "name": getattr(sp, "display_name", None)
                    or getattr(sp, "application_id", "unknown"),
                    "type": "service_principal",
                    "owner": getattr(sp, "display_name", "unknown"),
                    "active": bool(getattr(sp, "active", True)),
                    "application_id": getattr(sp, "application_id", None),
                    "entitlements": self._values(getattr(sp, "entitlements", None)),
                    "roles": self._values(getattr(sp, "roles", None)),
                    "tags": {},
                }
            )
        return resources

    @staticmethod
    def _values(items: Any) -> List[str]:
        """SCIM complex attributes are {value, display, ...}; rules want the values."""
        return sorted(
            {
                str(getattr(item, "value", "") or "")
                for item in (items or [])
                if getattr(item, "value", None)
            }
        )

    async def disable(self, resource_id: str, *, authorization=None) -> Dict[str, Any]:
        current = await asyncio.to_thread(
            self.workspace_client.service_principals.get, id=resource_id
        )
        undo_payload = {
            "resource_id": resource_id,
            "active": bool(getattr(current, "active", True)),
        }

        await asyncio.to_thread(
            self.workspace_client.service_principals.patch,
            id=resource_id,
            operations=[{"op": "replace", "path": "active", "value": "false"}],
        )
        logger.info("Deactivated service principal %s.", resource_id)
        return undo_payload

    async def enable(self, resource_id: str, undo_payload: Dict[str, Any]) -> bool:
        prior_active = undo_payload.get("active", True)
        await asyncio.to_thread(
            self.workspace_client.service_principals.patch,
            id=resource_id,
            operations=[
                {"op": "replace", "path": "active", "value": str(bool(prior_active)).lower()}
            ],
        )
        return True

    async def delete(self, resource_id: str, *, authorization) -> bool:
        return await asyncio.to_thread(
            destructive.delete_service_principal,
            self.workspace_client,
            resource_id,
            authorization=authorization,
        )
