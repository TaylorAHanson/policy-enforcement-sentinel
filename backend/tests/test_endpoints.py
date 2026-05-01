import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.main import app
from app.api.v1.endpoints.sentinel import run_history

client = TestClient(app)

@patch('app.api.v1.endpoints.sentinel.SentinelService')
def test_enforcement_action(MockSentinelService):
    mock_svc = MagicMock()
    
    async def mock_execute(*args, **kwargs):
        return {"success": True, "message": "Success"}
    mock_svc.execute_action = mock_execute
    
    MockSentinelService.return_value = mock_svc
    
    # Inject fake run
    run_history.append({"id": "run-123"})
    
    res = client.post("/api/v1/sentinel/runs/run-123/enforcement-action", json={
        "resource_id": "app-1",
        "resource_type": "app",
        "action": "KILL",
        "policy_name": "test_policy",
        "reason": "Test"
    })
    
    # Cleanup
    run_history.pop()
    
    assert res.status_code == 200
    assert res.json() == {"success": True, "message": "Success"}

@patch('app.api.v1.endpoints.policies.OpaProvider')
def test_evaluate_policy(MockOpa):
    mock_opa = MagicMock()
    async def mock_evaluate_content(*args, **kwargs):
        return {"is_violation": True}
    mock_opa.evaluate_content = mock_evaluate_content
    MockOpa.return_value = mock_opa
    
    res = client.post("/api/v1/policies/evaluate", json={
        "policy_name": "test.rego",
        "content": "package test\n\ndefault is_violation = true",
        "query": "data.test",
        "input_data": {"resource": {"id": "1"}}
    })
    
    assert res.status_code == 200
    assert res.json() == {"success": True, "result": {"is_violation": True}}
