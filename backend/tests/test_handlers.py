import pytest
from unittest.mock import MagicMock

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.providers.databricks.handlers.app_handler import AppResourceHandler
from app.providers.databricks.handlers.cluster_handler import ClusterResourceHandler
from app.providers.databricks.handlers.job_handler import JobResourceHandler
from app.providers.databricks.handlers.sql_warehouse_handler import SqlWarehouseResourceHandler
from app.providers.databricks.handlers.dashboard_handler import DashboardResourceHandler
from app.providers.databricks.handlers.genie_space_handler import GenieSpaceResourceHandler
from app.providers.databricks.handlers.model_serving_handler import ModelServingEndpointResourceHandler
from app.providers.databricks.handlers.pipeline_handler import PipelineResourceHandler
from app.providers.databricks.handlers.volume_handler import VolumeResourceHandler
from app.providers.databricks.handlers.dataset_handler import DatasetResourceHandler

@pytest.mark.asyncio
async def test_app_handler():
    mock_client = MagicMock()
    mock_app = MagicMock()
    mock_app.name = "test-app"
    mock_app.creator = "user@test.com"
    mock_app.active_deployment.state = "ACTIVE"
    mock_client.apps.list.return_value = [mock_app]

    handler = AppResourceHandler(mock_client)
    resources = await handler.discover()
    assert len(resources) == 1
    assert resources[0]["id"] == "test-app"
    
    # Test kill
    res = await handler.kill("test-app")
    assert res is True
    mock_client.apps.delete.assert_called_once_with(name="test-app")

@pytest.mark.asyncio
async def test_cluster_handler():
    mock_client = MagicMock()
    mock_cluster = MagicMock()
    mock_cluster.cluster_id = "test-cluster"
    mock_client.clusters.list.return_value = [mock_cluster]

    handler = ClusterResourceHandler(mock_client)
    resources = await handler.discover()
    assert len(resources) == 1
    
    res = await handler.kill("test-cluster")
    assert res is True
    mock_client.clusters.delete.assert_called_once_with(cluster_id="test-cluster")

@pytest.mark.asyncio
async def test_job_handler():
    mock_client = MagicMock()
    mock_job = MagicMock()
    mock_job.job_id = 123
    mock_client.jobs.list.return_value = [mock_job]

    handler = JobResourceHandler(mock_client)
    resources = await handler.discover()
    assert len(resources) == 1

    res = await handler.kill("123")
    assert res is True
    mock_client.jobs.delete.assert_called_once_with(job_id=123)

@pytest.mark.asyncio
async def test_sql_warehouse_handler():
    mock_client = MagicMock()
    mock_wh = MagicMock()
    mock_wh.id = "wh-123"
    mock_client.warehouses.list.return_value = [mock_wh]

    handler = SqlWarehouseResourceHandler(mock_client)
    resources = await handler.discover()
    assert len(resources) == 1

    res = await handler.kill("wh-123")
    assert res is True
    mock_client.warehouses.delete.assert_called_once_with(id="wh-123")

@pytest.mark.asyncio
async def test_model_serving_handler():
    mock_client = MagicMock()
    mock_ep = MagicMock()
    mock_ep.name = "ep-123"
    mock_client.serving_endpoints.list.return_value = [mock_ep]

    handler = ModelServingEndpointResourceHandler(mock_client)
    resources = await handler.discover()
    assert len(resources) == 1

    res = await handler.kill("ep-123")
    assert res is True
    mock_client.serving_endpoints.delete.assert_called_once_with(name="ep-123")

@pytest.mark.asyncio
async def test_pipeline_handler():
    mock_client = MagicMock()
    mock_pipeline = MagicMock()
    mock_pipeline.pipeline_id = "pl-123"
    mock_client.pipelines.list_pipelines.return_value = [mock_pipeline]
    mock_client.pipelines.get.return_value = mock_pipeline

    handler = PipelineResourceHandler(mock_client)
    resources = await handler.discover()
    assert len(resources) == 1

    res = await handler.kill("pl-123")
    assert res is True
    mock_client.pipelines.delete.assert_called_once_with(pipeline_id="pl-123")
