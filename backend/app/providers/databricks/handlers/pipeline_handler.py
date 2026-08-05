import asyncio
import logging
from typing import Any, Dict, List

from app.providers.databricks import destructive, permissions
from app.providers.databricks.handlers.base import (
    BaseResourceHandler,
    SupportsDelete,
    SupportsDisable,
    SupportsRevokeAccess,
)

logger = logging.getLogger(__name__)


class PipelineResourceHandler(
    BaseResourceHandler, SupportsDisable, SupportsRevokeAccess, SupportsDelete
):
    """Spark Declarative Pipelines.

    A continuous pipeline burning compute is best handled by switching it to
    triggered, which stops the spend without losing the pipeline or its state.
    """

    resource_type = "pipeline"

    async def discover(self) -> List[Dict[str, Any]]:
        resources = []
        for pipeline in self.workspace_client.pipelines.list_pipelines():
            # list_pipelines returns a summary; the policy needs spec details.
            # A failure on one pipeline shouldn't abandon the rest, but it also
            # shouldn't silently present that pipeline as compliant, so it is
            # recorded with what we know and flagged as incomplete.
            try:
                details = await asyncio.to_thread(
                    self.workspace_client.pipelines.get, pipeline_id=pipeline.pipeline_id
                )
                spec = getattr(details, "spec", None)
                tags = dict(getattr(spec, "tags", None) or {}) if spec else {}
                resources.append(
                    {
                        "id": pipeline.pipeline_id,
                        "name": pipeline.name,
                        "type": "pipeline",
                        "owner": getattr(pipeline, "creator_user_name", "unknown"),
                        "serverless": bool(getattr(spec, "serverless", False)) if spec else False,
                        "continuous": bool(getattr(spec, "continuous", False)) if spec else False,
                        "channel": str(getattr(spec, "channel", "CURRENT")) if spec else "CURRENT",
                        "development": bool(getattr(spec, "development", False)) if spec else False,
                        "tags": tags,
                        "metadata_complete": True,
                    }
                )
            except Exception as e:
                logger.warning(
                    "Could not fetch spec for pipeline %s: %s", pipeline.pipeline_id, e
                )
                resources.append(
                    {
                        "id": pipeline.pipeline_id,
                        "name": pipeline.name,
                        "type": "pipeline",
                        "owner": getattr(pipeline, "creator_user_name", "unknown"),
                        "tags": {},
                        "metadata_complete": False,
                    }
                )
        return resources

    async def disable(self, resource_id: str, *, authorization=None) -> Dict[str, Any]:
        details = await asyncio.to_thread(
            self.workspace_client.pipelines.get, pipeline_id=resource_id
        )
        spec = getattr(details, "spec", None)
        undo_payload = {
            "resource_id": resource_id,
            "continuous": bool(getattr(spec, "continuous", False)) if spec else False,
        }

        await asyncio.to_thread(
            self.workspace_client.pipelines.update,
            pipeline_id=resource_id,
            continuous=False,
        )
        logger.info("Switched pipeline %s from continuous to triggered.", resource_id)
        return undo_payload

    async def enable(self, resource_id: str, undo_payload: Dict[str, Any]) -> bool:
        await asyncio.to_thread(
            self.workspace_client.pipelines.update,
            pipeline_id=resource_id,
            continuous=bool(undo_payload.get("continuous", False)),
        )
        return True

    async def revoke_access(self, resource_id: str, *, authorization=None) -> Dict[str, Any]:
        return await asyncio.to_thread(
            permissions.revoke_permissions, self.workspace_client, "pipeline", resource_id
        )

    async def restore_access(self, resource_id: str, undo_payload: Dict[str, Any]) -> bool:
        return await asyncio.to_thread(
            permissions.restore_permissions, self.workspace_client, undo_payload
        )

    async def delete(self, resource_id: str, *, authorization) -> bool:
        return await asyncio.to_thread(
            destructive.delete_pipeline,
            self.workspace_client,
            resource_id,
            authorization=authorization,
        )
