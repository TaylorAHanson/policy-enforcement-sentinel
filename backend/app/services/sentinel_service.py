import asyncio
import logging
from typing import Dict, Any, List
import uuid
from datetime import datetime
from app.core.config import settings
from app.providers.databricks.client import DatabricksProvider
from app.providers.opa.client import OpaProvider

from app.providers.databricks.handlers import (
    AppResourceHandler,
    ClusterResourceHandler,
    JobResourceHandler,
    SqlWarehouseResourceHandler,
    DashboardResourceHandler,
    GenieSpaceResourceHandler,
    ServicePrincipalResourceHandler,
    NotebookResourceHandler,
    VolumeResourceHandler,
    DatasetResourceHandler
)
import glob
import os

logger = logging.getLogger(__name__)

class SentinelService:
    def __init__(self):
        self.opa_provider = OpaProvider(settings.opa_provider_config())
        self.db_provider = DatabricksProvider(
            host=settings.DATABRICKS_HOST or settings.DATABRICKS_WORKSPACE_URL or "",
            client_id=settings.DATABRICKS_CLIENT_ID,
            client_secret=settings.DATABRICKS_CLIENT_SECRET,
            token=settings.DATABRICKS_TOKEN
        )

    async def run_discovery_and_evaluation(self, workspace_name: str, environment: str, mode: str = "audit") -> Dict[str, Any]:
        """
        Discovers resources across the workspace and evaluates them against all policies.
        """
        logger.info(f"Starting discovery for workspace {workspace_name}")
        
        try:
            workspace_client = self.db_provider.client
        except Exception as e:
            logger.error(f"Failed to init Databricks client: {e}")
            return {"error": str(e), "violations": []}

        handler_classes = [
            AppResourceHandler,
            ClusterResourceHandler,
            JobResourceHandler,
            SqlWarehouseResourceHandler,
            DashboardResourceHandler,
            GenieSpaceResourceHandler,
            ServicePrincipalResourceHandler,
            NotebookResourceHandler,
            VolumeResourceHandler,
            DatasetResourceHandler
        ]

        discovered_resources = []
        
        async def _safe_discover(h_class):
            handler = h_class(workspace_client)
            try:
                return await handler.discover()
            except Exception as e:
                logger.error(f"Error discovering resources with {h_class.__name__}: {e}")
                return []

        results = await asyncio.gather(*[_safe_discover(h) for h in handler_classes])
        for resources in results:
            if resources:
                discovered_resources.extend(resources)

        logger.info(f"Discovered {len(discovered_resources)} resources. Evaluating policies...")

        workspace_type = "enterprise" if "enterprise" in workspace_name else "domain"
        
        policy_files = glob.glob(os.path.join(settings.POLICIES_DIR, "*.rego"))
        violations = []
        
        semaphore = asyncio.Semaphore(50)

        async def _evaluate_policy(resource, policy_path):
            async with semaphore:
                policy_name = os.path.basename(policy_path).replace(".rego", "")
                query = f"data.databricks.governance.{policy_name}"
                input_data = {
                    "workspace": {"name": workspace_name, "type": workspace_type, "environment": environment},
                    "resource": resource,
                    "request_time": datetime.utcnow().isoformat(),
                    "allowlist_records": [] # Could be hydrated from DB
                }
                try:
                    result = await self.opa_provider.evaluate(
                        policy_path=policy_path,
                        query=query,
                        input_data=input_data
                    )

                    is_violation = result.get("is_violation")
                    action = result.get("action", "KILL")

                    if is_violation or action in ["CERTIFY", "UNCERTIFY"]:
                        return {
                            "id": str(uuid.uuid4()),
                            "resource_id": resource.get("id"),
                            "resource_type": resource.get("type"),
                            "policy": policy_name,
                            "action": action,
                            "reason": result.get("reason", "Unknown violation"),
                            "severity": result.get("severity", "HIGH"),
                            "resource_details": resource
                        }
                except Exception as e:
                    logger.error(f"Error evaluating {policy_name} on {resource.get('id')}: {e}")
                return None

        evaluation_tasks = []
        for resource in discovered_resources:
            for policy_path in policy_files:
                evaluation_tasks.append(_evaluate_policy(resource, policy_path))

        if evaluation_tasks:
            eval_results = await asyncio.gather(*evaluation_tasks)
            for res in eval_results:
                if res:
                    violations.append(res)

        if mode == "enforce" and violations:
            logger.info("Running in enforce mode. Executing remediations...")
            handlers_map = {
                "app": AppResourceHandler(workspace_client),
                "cluster": ClusterResourceHandler(workspace_client),
                "job": JobResourceHandler(workspace_client),
                "sql_warehouse": SqlWarehouseResourceHandler(workspace_client),
                "dashboard": DashboardResourceHandler(workspace_client),
                "genie_space": GenieSpaceResourceHandler(workspace_client),
                "service_principal": ServicePrincipalResourceHandler(workspace_client),
                "notebook": NotebookResourceHandler(workspace_client),
                "storage": VolumeResourceHandler(workspace_client),
                "table": DatasetResourceHandler(workspace_client),
                "data_product": DatasetResourceHandler(workspace_client),
            }

            async def _enforce(violation):
                action = violation.get("action", "KILL")
                resource_type = violation.get("resource_type")
                resource_id = violation.get("resource_id")
                reason = violation.get("reason", "Policy violation")
                
                handler = handlers_map.get(resource_type)
                if not handler:
                    logger.warning(f"No handler for {resource_type}, skipping enforcement")
                    return
                
                try:
                    if action == "KILL":
                        if hasattr(handler, "kill"):
                            await handler.kill(resource_id)
                    elif action == "WARN":
                        if hasattr(handler, "warn"):
                            await handler.warn(resource_id, reason)
                    elif action == "CERTIFY":
                        if hasattr(handler, "certify"):
                            await handler.certify(resource_id)
                    elif action == "UNCERTIFY":
                        if hasattr(handler, "uncertify"):
                            await handler.uncertify(resource_id)
                except Exception as e:
                    logger.error(f"Failed to enforce {action} on {resource_id}: {e}")

            enforce_tasks = []
            for v in violations:
                enforce_tasks.append(_enforce(v))
            
            if enforce_tasks:
                await asyncio.gather(*enforce_tasks)

        return {
            "total_scanned": len(discovered_resources),
            "total_violations": len(violations),
            "violations": violations
        }
