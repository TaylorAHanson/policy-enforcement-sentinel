import asyncio
import logging
from typing import Any, Dict, List

from app.providers.databricks import destructive, permissions
from app.providers.databricks.handlers.base import (
    BaseResourceHandler,
    SupportsRevokeAccess,
    SupportsTerminate,
    SupportsThrottle,
)

logger = logging.getLogger(__name__)


class ClusterResourceHandler(
    BaseResourceHandler, SupportsRevokeAccess, SupportsThrottle, SupportsTerminate
):
    """Interactive and job clusters.

    Terminating a cluster destroys whatever is running on it, so the preferred
    responses are revoking access (stops further misuse) and throttling (caps
    the spend). Termination is available but sits behind every gate.
    """

    resource_type = "cluster"

    async def discover(self) -> List[Dict[str, Any]]:
        resources = []
        # Errors propagate on purpose: an auth failure here must not look like
        # a workspace with no clusters.
        for cluster in self.workspace_client.clusters.list():
            state = getattr(cluster, "state", None)
            resources.append(
                {
                    "id": cluster.cluster_id,
                    "name": cluster.cluster_name,
                    "type": "cluster",
                    "owner": getattr(cluster, "creator_user_name", "unknown"),
                    "state": getattr(state, "value", "UNKNOWN") if state else "UNKNOWN",
                    "cluster_type": (
                        "job" if getattr(cluster, "cluster_source", None) == "JOB" else "interactive"
                    ),
                    "access_mode": str(getattr(cluster, "data_security_mode", "") or ""),
                    "autotermination_minutes": getattr(cluster, "autotermination_minutes", None),
                    "policy_id": getattr(cluster, "policy_id", None),
                    "num_workers": getattr(cluster, "num_workers", None),
                    "autoscale_max_workers": getattr(
                        getattr(cluster, "autoscale", None), "max_workers", None
                    ),
                    "tags": dict(getattr(cluster, "custom_tags", None) or {}),
                }
            )
        return resources

    # --- Tier 2 -----------------------------------------------------------

    async def revoke_access(self, resource_id: str, *, authorization=None) -> Dict[str, Any]:
        return await asyncio.to_thread(
            permissions.revoke_permissions, self.workspace_client, "cluster", resource_id
        )

    async def restore_access(self, resource_id: str, undo_payload: Dict[str, Any]) -> bool:
        return await asyncio.to_thread(
            permissions.restore_permissions, self.workspace_client, undo_payload
        )

    async def throttle(self, resource_id: str, *, authorization=None) -> Dict[str, Any]:
        """Cap spend by forcing autotermination on, without stopping the cluster."""
        current = await asyncio.to_thread(
            self.workspace_client.clusters.get, cluster_id=resource_id
        )
        undo_payload = {
            "resource_id": resource_id,
            "autotermination_minutes": getattr(current, "autotermination_minutes", None),
            "autoscale_max_workers": getattr(
                getattr(current, "autoscale", None), "max_workers", None
            ),
        }

        await asyncio.to_thread(
            self.workspace_client.clusters.edit,
            cluster_id=resource_id,
            cluster_name=current.cluster_name,
            spark_version=current.spark_version,
            node_type_id=current.node_type_id,
            num_workers=getattr(current, "num_workers", None),
            autotermination_minutes=30,
        )
        logger.info("Throttled cluster %s: autotermination set to 30 minutes.", resource_id)
        return undo_payload

    async def unthrottle(self, resource_id: str, undo_payload: Dict[str, Any]) -> bool:
        current = await asyncio.to_thread(
            self.workspace_client.clusters.get, cluster_id=resource_id
        )
        await asyncio.to_thread(
            self.workspace_client.clusters.edit,
            cluster_id=resource_id,
            cluster_name=current.cluster_name,
            spark_version=current.spark_version,
            node_type_id=current.node_type_id,
            num_workers=getattr(current, "num_workers", None),
            autotermination_minutes=undo_payload.get("autotermination_minutes"),
        )
        return True

    # --- Tier 3 -----------------------------------------------------------

    async def terminate(self, resource_id: str, *, authorization) -> bool:
        return await asyncio.to_thread(
            destructive.terminate_cluster,
            self.workspace_client,
            resource_id,
            authorization=authorization,
        )
