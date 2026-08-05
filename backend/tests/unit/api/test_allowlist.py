import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.main import app

client = TestClient(app)

def test_allowlist_crud():
    # Create
    new_entry = {
        "resource_id": "cluster-1",
        "resource_type": "cluster",
        "workspace": "ws-test",
        "justification": "Testing"
    }
    res = client.post("/api/v1/allowlist/", json=new_entry)
    assert res.status_code == 200
    data = res.json()
    entry_id = data["id"]
    assert data["resource_id"] == "cluster-1"

    # Read all
    res = client.get("/api/v1/allowlist/")
    assert res.status_code == 200
    entries = res.json()
    assert len(entries) > 0
    assert any(e["id"] == entry_id for e in entries)

    # Delete
    res = client.delete(f"/api/v1/allowlist/{entry_id}")
    assert res.status_code == 200

    # Verify deleted
    res = client.get("/api/v1/allowlist/")
    entries = res.json()
    assert not any(e["id"] == entry_id for e in entries)
