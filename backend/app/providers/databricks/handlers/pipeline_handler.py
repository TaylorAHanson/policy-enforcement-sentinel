import logging
from typing import List, Dict, Any
from app.providers.databricks.handlers.base import BaseResourceHandler

logger = logging.getLogger(__name__)

class PipelineResourceHandler(BaseResourceHandler):
    async def discover(self) -> List[Dict[str, Any]]:
        resources = []
        try:
            pipelines = self.workspace_client.pipelines.list_pipelines()
            for pipeline in pipelines:
                try:
                    # list_pipelines only returns minimal info, fetch full details
                    details = self.workspace_client.pipelines.get(pipeline_id=pipeline.pipeline_id)
                    
                    serverless = False
                    if details.spec and hasattr(details.spec, 'serverless'):
                        serverless = details.spec.serverless
                        
                    continuous = False
                    if details.spec and hasattr(details.spec, 'continuous'):
                        continuous = details.spec.continuous
                        
                    channel = "CURRENT"
                    if details.spec and hasattr(details.spec, 'channel'):
                        channel = details.spec.channel
                    
                    tags_dict = {}
                    # Note: pipelines tags might be under spec.cluster or at top level depending on the Spark Declarative Pipelines version.
                    # Best effort to grab simple spec tags
                    if details.spec and getattr(details.spec, 'tags', None):
                        for tag_key, tag_value in getattr(details.spec, 'tags', {}).items():
                            tags_dict[tag_key] = tag_value
                    
                    resources.append({
                        "id": pipeline.pipeline_id,
                        "type": "pipeline",
                        "attributes": {
                            "name": pipeline.name,
                            "creator": getattr(pipeline, 'creator_user_name', 'unknown'),
                            "serverless": serverless,
                            "continuous": continuous,
                            "channel": str(channel),
                            "custom_tags": tags_dict
                        }
                    })
                except Exception as inner_e:
                    logger.warning(f"Failed to fetch details for pipeline {pipeline.pipeline_id}: {inner_e}")
                    
        except Exception as e:
            logger.error(f"Failed to discover Spark Declarative pipelines: {e}")
        return resources
        
    async def kill(self, resource_id: str) -> bool:
        try:
            self.workspace_client.pipelines.delete(pipeline_id=resource_id)
            return True
        except Exception as e:
            logger.error(f"Failed to delete pipeline {resource_id}: {e}")
            return False

    async def warn(self, resource_id: str, message: str) -> bool:
        logger.info(f"Warning owner of pipeline {resource_id}: {message}")
        return True