import asyncio
import logging
from typing import Any, Dict, List

from app.core.config import settings
from app.providers.databricks import destructive
from app.providers.databricks.handlers.base import BaseResourceHandler, SupportsDelete

logger = logging.getLogger(__name__)


class NotebookResourceHandler(BaseResourceHandler, SupportsDelete):
    """Workspace notebooks.

    Walking the workspace tree is expensive, so this is gated behind
    ``SENTINEL_SCAN_NOTEBOOKS`` and off by default.
    """

    resource_type = "notebook"

    async def discover(self) -> List[Dict[str, Any]]:
        if not settings.SENTINEL_SCAN_NOTEBOOKS:
            logger.debug("Notebook scanning disabled (SENTINEL_SCAN_NOTEBOOKS is off).")
            return []

        from databricks.sdk.service import workspace as workspace_service

        resources: List[Dict[str, Any]] = []
        for base_path in ("/Users", "/Shared"):
            try:
                objects = await asyncio.to_thread(
                    lambda p=base_path: list(
                        self.workspace_client.workspace.list(path=p, recursive=True)
                    )
                )
            except Exception as e:
                # One inaccessible root shouldn't abandon the other.
                logger.warning("Could not list notebooks under %s: %s", base_path, e)
                continue

            for obj in objects:
                if getattr(obj, "object_type", None) != workspace_service.ObjectType.NOTEBOOK:
                    continue
                path = obj.path
                # /Users/<email>/... is the only reliable ownership signal the
                # workspace API gives us without a per-object ACL lookup.
                owner = "unknown"
                if path.startswith("/Users/"):
                    parts = path.split("/")
                    if len(parts) > 2:
                        owner = parts[2]

                resources.append(
                    {
                        "id": path,
                        "name": path.rsplit("/", 1)[-1],
                        "type": "notebook",
                        "owner": owner,
                        "language": str(getattr(obj, "language", "") or ""),
                        "in_shared": path.startswith("/Shared"),
                        "tags": {},
                    }
                )
        return resources

    async def delete(self, resource_id: str, *, authorization) -> bool:
        return await asyncio.to_thread(
            destructive.delete_notebook,
            self.workspace_client,
            resource_id,
            authorization=authorization,
        )
