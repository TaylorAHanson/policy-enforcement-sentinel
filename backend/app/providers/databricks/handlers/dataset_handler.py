import asyncio
import logging
from typing import Any, Dict, List

from app.providers.databricks import uc_metadata
from app.providers.databricks.handlers.base import (
    BaseResourceHandler,
    SupportsCertification,
    SupportsQuarantine,
)

logger = logging.getLogger(__name__)

#: Tag key the Sentinel uses to record certification state on a table.
CERTIFICATION_TAG = "sentinel_certified"
QUARANTINE_TAG = "sentinel_quarantined"


class DatasetResourceHandler(BaseResourceHandler, SupportsCertification, SupportsQuarantine):
    """Unity Catalog tables.

    There is no destructive capability here at all, deliberately. Dropping a
    table is not a governance remediation, it is data loss; the strongest thing
    this handler can do is withdraw certification and strip grants, both of
    which are reversible.
    """

    resource_type = "dataset"

    async def discover(self) -> List[Dict[str, Any]]:
        catalogs = [
            catalog.name
            for catalog in self.workspace_client.catalogs.list()
            # System and sample catalogs aren't ours to govern.
            if catalog.name not in ("system", "samples", "__databricks_internal")
        ]
        if not catalogs:
            return []

        metadata = await asyncio.to_thread(
            uc_metadata.fetch_uc_metadata, self.workspace_client, catalogs
        )

        resources: List[Dict[str, Any]] = []
        for full_name, entry in metadata.items():
            tags = entry.get("tags", {})
            resources.append(
                {
                    "id": full_name,
                    "name": entry.get("name"),
                    "type": "dataset",
                    "owner": entry.get("owner", "unknown"),
                    "catalog": entry.get("catalog"),
                    "schema": entry.get("schema"),
                    "table_type": entry.get("table_type"),
                    "has_description": bool((entry.get("comment") or "").strip()),
                    "certified": str(tags.get(CERTIFICATION_TAG, "")).lower() == "true",
                    "quarantined": str(tags.get(QUARANTINE_TAG, "")).lower() == "true",
                    "last_altered": str(entry.get("last_altered") or ""),
                    "tags": tags,
                }
            )
        return resources

    # --- Certification ----------------------------------------------------

    async def certify(self, resource_id: str, *, authorization=None) -> Dict[str, Any]:
        await self._set_tag(resource_id, CERTIFICATION_TAG, "true")
        return {"resource_id": resource_id, "certified": False}

    async def uncertify(self, resource_id: str, *, authorization=None) -> Dict[str, Any]:
        await self._set_tag(resource_id, CERTIFICATION_TAG, "false")
        return {"resource_id": resource_id, "certified": True}

    # --- Quarantine -------------------------------------------------------

    async def quarantine(self, resource_id: str, *, authorization=None) -> Dict[str, Any]:
        from databricks.sdk.service import catalog as catalog_service

        current = await asyncio.to_thread(
            self.workspace_client.grants.get,
            securable_type=catalog_service.SecurableType.TABLE,
            full_name=resource_id,
        )
        prior = [
            {
                "principal": assignment.principal,
                "privileges": [
                    str(getattr(p, "value", p)) for p in (assignment.privileges or [])
                ],
            }
            for assignment in (getattr(current, "privilege_assignments", None) or [])
        ]

        changes = [
            catalog_service.PermissionsChange(
                principal=entry["principal"],
                remove=[catalog_service.Privilege(p) for p in entry["privileges"]],
            )
            for entry in prior
        ]
        if changes:
            await asyncio.to_thread(
                self.workspace_client.grants.update,
                securable_type=catalog_service.SecurableType.TABLE,
                full_name=resource_id,
                changes=changes,
            )
        await self._set_tag(resource_id, QUARANTINE_TAG, "true")
        logger.info("Quarantined table %s: %d grant(s) removed.", resource_id, len(prior))
        return {"resource_id": resource_id, "privilege_assignments": prior}

    async def unquarantine(self, resource_id: str, undo_payload: Dict[str, Any]) -> bool:
        from databricks.sdk.service import catalog as catalog_service

        changes = [
            catalog_service.PermissionsChange(
                principal=entry["principal"],
                add=[catalog_service.Privilege(p) for p in entry["privileges"]],
            )
            for entry in undo_payload.get("privilege_assignments", [])
        ]
        if changes:
            await asyncio.to_thread(
                self.workspace_client.grants.update,
                securable_type=catalog_service.SecurableType.TABLE,
                full_name=undo_payload["resource_id"],
                changes=changes,
            )
        await self._set_tag(undo_payload["resource_id"], QUARANTINE_TAG, "false")
        return True

    async def _set_tag(self, full_name: str, key: str, value: str) -> None:
        """Tags on UC tables are set through SQL rather than the REST API."""
        warehouse_id = await asyncio.to_thread(
            uc_metadata.pick_warehouse, self.workspace_client
        )
        if not warehouse_id:
            raise RuntimeError(
                f"No SQL warehouse available to set tag {key!r} on {full_name}"
            )

        await asyncio.to_thread(
            self.workspace_client.statement_execution.execute_statement,
            warehouse_id=warehouse_id,
            statement=f"ALTER TABLE {full_name} SET TAGS ('{key}' = '{value}')",
            wait_timeout="30s",
        )
