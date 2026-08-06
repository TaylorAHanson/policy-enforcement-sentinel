import asyncio
import logging
from typing import Any, Dict, List

from app.providers.databricks import activity, uc_metadata
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

    discovered_fields = {
        "id": "The three-level full name, catalog.schema.table.",
        "name": "The table name.",
        "type": 'Always "dataset".',
        "owner": "The Unity Catalog owner.",
        "catalog": "The containing catalog.",
        "schema": "The containing schema.",
        "table_type": "MANAGED, EXTERNAL, VIEW and so on.",
        "has_description": "Whether the table comment is non-empty.",
        "certified": "Whether the certification tag is set.",
        "quarantined": "Whether the quarantine tag is set.",
        "last_altered": "Timestamp of the last change, as a string. May be empty.",
        "idle_days": (
            "Days since the table was last **written to**, from `last_altered`. "
            "Note this is not days since it was last read — a table queried "
            "daily but never updated will look idle."
        ),
        "all_columns_have_descriptions": (
            "Whether every column carries a comment. True when the column read "
            "failed, so a rule about undescribed columns stays quiet rather "
            "than flagging a table nobody could inspect."
        ),
        # Deliberately not collected: `principals` and `grants`. Unity Catalog
        # only discloses another principal's grants to the object's owner or a
        # metastore admin, and this scanner is neither. `table_privileges` would
        # return the scanner's own access and nothing else, making every table
        # look correctly restricted.
        "tags": "Unity Catalog tags as a string map.",
    }

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
            resource = {
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
                # None means the column read failed. True is the safe
                # reading of "we don't know" for a rule that fires on False.
                "all_columns_have_descriptions": (
                    True
                    if entry.get("all_columns_have_descriptions") is None
                    else bool(entry["all_columns_have_descriptions"])
                ),
                "tags": tags,
            }
            resources.append(
                activity.merge_idle_days(
                    resource, activity.days_since_timestamp(entry.get("last_altered"))
                )
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
