import pytest
from fastapi.testclient import TestClient
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.main import app

client = TestClient(app)

def test_get_readme():
    res = client.get("/api/v1/readme/")
    assert res.status_code == 200
    data = res.json()
    assert "content" in data
    assert "# Policy Enforcement Sentinel" in data["content"]
