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


class DashboardResourceHandler(BaseResourceHandler, SupportsRevokeAccess, SupportsDelete):
    """Lakeview dashboards.

    The common violation is a dashboard published with embedded credentials and
    shared broadly, which lets any viewer query as the publisher. Revoking the
    broad share fixes exactly that without trashing someone's work.
    """

    resource_type = "dashboard"

    discovered_fields = {
        "id": "The dashboard ID.",
        "name": "The dashboard's display name.",
        "type": 'Always "dashboard".',
        "owner": "The email of whoever created the dashboard.",
        "uses_embedded_credentials": "Whether the published dashboard runs as its publisher.",
        "is_published": (
            "Whether a published version exists. False also when the published "
            "lookup failed, so a rule using it should be about published "
            "dashboards rather than about drafts."
        ),
        "shared_with": 'Group names it is shared with. Contains "ALL_USERS" when shared workspace-wide.',
        "tags": "Always empty. Lakeview dashboards carry no tags.",
    }

    async def discover(self) -> List[Dict[str, Any]]:
        resources = []
        for dash in self.workspace_client.lakeview.list():
            uses_embedded_credentials = getattr(dash, "uses_embedded_credentials", False)
            shared_with: List[str] = list(getattr(dash, "shared_with", None) or [])
            is_published = False

            # These two lookups are per-dashboard enrichment, not discovery. A
            # failure means we know less about one dashboard, not that discovery
            # failed, so they stay guarded while the outer loop does not.
            try:
                published = await asyncio.to_thread(
                    self.workspace_client.lakeview.get_published, dash.dashboard_id
                )
                # Reaching here at all means a published version exists; the API
                # raises rather than returning an empty answer when it does not.
                is_published = True
                if getattr(published, "embed_credentials", False):
                    uses_embedded_credentials = True
            except Exception as e:
                logger.debug(
                    "Could not fetch published status for dashboard %s: %s",
                    dash.dashboard_id,
                    e,
                )

            try:
                perms = await asyncio.to_thread(
                    self.workspace_client.workspace.get_permissions,
                    "dashboards",
                    dash.dashboard_id,
                )
                for entry in getattr(perms, "access_control_list", None) or []:
                    group_name = getattr(entry, "group_name", None)
                    if not group_name:
                        continue
                    if group_name.lower() in ("users", "account users", "all_users"):
                        shared_with.append("ALL_USERS")
                    else:
                        shared_with.append(group_name)
            except Exception as e:
                logger.debug(
                    "Could not fetch permissions for dashboard %s: %s", dash.dashboard_id, e
                )
                # Seeing the dashboard but being denied its ACL means we hold
                # viewer rights without CAN_MANAGE, which in practice means it
                # was shared broadly. Infer that rather than under-report.
                if uses_embedded_credentials and (
                    "does not have CAN_MANAGE permissions" in str(e) or "403" in str(e)
                ):
                    shared_with.append("ALL_USERS")

            resources.append(
                {
                    "id": dash.dashboard_id,
                    "name": dash.display_name,
                    "type": "dashboard",
                    "owner": getattr(dash, "creator_user_name", "unknown"),
                    "uses_embedded_credentials": uses_embedded_credentials,
                    "is_published": is_published,
                    "shared_with": sorted(set(shared_with)),
                    "tags": {},
                }
            )
        return resources

    async def revoke_access(self, resource_id: str, *, authorization=None) -> Dict[str, Any]:
        return await asyncio.to_thread(
            permissions.revoke_permissions, self.workspace_client, "dashboard", resource_id
        )

    async def restore_access(self, resource_id: str, undo_payload: Dict[str, Any]) -> bool:
        return await asyncio.to_thread(
            permissions.restore_permissions, self.workspace_client, undo_payload
        )

    async def delete(self, resource_id: str, *, authorization) -> bool:
        return await asyncio.to_thread(
            destructive.trash_dashboard,
            self.workspace_client,
            resource_id,
            authorization=authorization,
        )
