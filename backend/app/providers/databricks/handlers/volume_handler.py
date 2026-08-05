import asyncio
import logging
from typing import Any, Dict, List

from app.providers.databricks import destructive
from app.providers.databricks.handlers.base import (
    BaseResourceHandler,
    SupportsDelete,
    SupportsQuarantine,
)

logger = logging.getLogger(__name__)


class VolumeResourceHandler(BaseResourceHandler, SupportsQuarantine, SupportsDelete):
    """Unity Catalog volumes.

    Deleting a volume destroys the data in it, so the response to a
    non-compliant volume is to quarantine it — strip grants down to the owner
    so nothing new can be written or read through it.
    """

    resource_type = "storage"

    async def discover(self) -> List[Dict[str, Any]]:
        resources: List[Dict[str, Any]] = []
        for catalog in self.workspace_client.catalogs.list():
            try:
                schemas = await asyncio.to_thread(
                    lambda c=catalog.name: list(self.workspace_client.schemas.list(catalog_name=c))
                )
            except Exception as e:
                # A catalog we can't read is worth noting but shouldn't sink the
                # scan of every other catalog.
                logger.warning("Could not list schemas in catalog %s: %s", catalog.name, e)
                continue

            for schema in schemas:
                try:
                    volumes = await asyncio.to_thread(
                        lambda c=catalog.name, s=schema.name: list(
                            self.workspace_client.volumes.list(catalog_name=c, schema_name=s)
                        )
                    )
                except Exception as e:
                    logger.debug(
                        "Could not list volumes in %s.%s: %s", catalog.name, schema.name, e
                    )
                    continue

                for volume in volumes:
                    resources.append(
                        {
                            "id": volume.full_name,
                            "name": volume.name,
                            "type": "storage",
                            "storage_type": str(getattr(volume, "volume_type", "") or "volume"),
                            "owner": getattr(volume, "owner", "unknown"),
                            "catalog": catalog.name,
                            "schema": schema.name,
                            "tags": {},
                        }
                    )
        return resources

    async def quarantine(self, resource_id: str, *, authorization=None) -> Dict[str, Any]:
        from databricks.sdk.service import catalog as catalog_service

        current = await asyncio.to_thread(
            self.workspace_client.grants.get,
            securable_type=catalog_service.SecurableType.VOLUME,
            full_name=resource_id,
        )
        prior = [
            {
                "principal": assignment.principal,
                "privileges": [str(getattr(p, "value", p)) for p in (assignment.privileges or [])],
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
                securable_type=catalog_service.SecurableType.VOLUME,
                full_name=resource_id,
                changes=changes,
            )
        logger.info("Quarantined volume %s: %d grant(s) removed.", resource_id, len(prior))
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
                securable_type=catalog_service.SecurableType.VOLUME,
                full_name=undo_payload["resource_id"],
                changes=changes,
            )
        return True

    async def delete(self, resource_id: str, *, authorization) -> bool:
        return await asyncio.to_thread(
            destructive.delete_volume,
            self.workspace_client,
            resource_id,
            authorization=authorization,
        )
