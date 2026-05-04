import logging
from typing import List, Dict, Any
from app.providers.databricks.handlers.base import BaseResourceHandler

logger = logging.getLogger(__name__)

class ModelServingEndpointResourceHandler(BaseResourceHandler):
    async def discover(self) -> List[Dict[str, Any]]:
        resources = []
        try:
            endpoints = self.workspace_client.serving_endpoints.list()
            for ep in endpoints:
                # Convert tags
                tags_dict = {}
                if getattr(ep, 'tags', None):
                    for tag in ep.tags:
                        if hasattr(tag, 'key'):
                            tags_dict[tag.key] = getattr(tag, 'value', '')
                
                resources.append({
                    "id": ep.name,
                    "type": "model_serving_endpoint",
                    "attributes": {
                        "name": ep.name,
                        "creator": getattr(ep, 'creator', 'unknown'),
                        "endpoint_type": getattr(ep, 'endpoint_type', 'unknown'), # Could be PROVISIONED, SERVERLESS
                        "custom_tags": tags_dict
                    }
                })
        except Exception as e:
            logger.error(f"Failed to discover model serving endpoints: {e}")
        return resources
        
    async def kill(self, resource_id: str) -> bool:
        try:
            self.workspace_client.serving_endpoints.delete(name=resource_id)
            return True
        except Exception as e:
            logger.error(f"Failed to delete model serving endpoint {resource_id}: {e}")
            return False

    async def warn(self, resource_id: str, message: str, owner: str = "unknown") -> bool:
        from app.providers.notifications.email import EmailNotifier
        logger.info(f"Warning owner of model serving endpoint {resource_id}: {message}")
        return EmailNotifier().send_warning(owner, resource_id, message)