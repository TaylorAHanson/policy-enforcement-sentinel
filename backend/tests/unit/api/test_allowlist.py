"""Allowlist CRUD, against the in-memory database.

The previous version of this file used a module-level TestClient, which meant it
created and deleted rows in the developer's real ``sentinel.db``. The `client`
fixture points every session at a transaction that is rolled back.
"""
from datetime import datetime, timedelta

from tests.factories import AllowlistFactory


def test_create_read_delete(client):
    created = client.post(
        "/api/v1/allowlist/",
        json={
            "resource_id": "cluster-1",
            "resource_type": "cluster",
            "workspace": "prod-analytics",
            "justification": "Approved for the migration window.",
        },
    )
    assert created.status_code == 200
    entry_id = created.json()["id"]
    assert created.json()["resource_id"] == "cluster-1"

    listed = client.get("/api/v1/allowlist/")
    assert listed.status_code == 200
    assert any(e["id"] == entry_id for e in listed.json())

    assert client.delete(f"/api/v1/allowlist/{entry_id}").status_code == 200
    assert not any(e["id"] == entry_id for e in client.get("/api/v1/allowlist/").json())


def test_an_expiry_round_trips(client, db_session):
    """Expiry is what makes an exception temporary, so it has to survive the API."""
    expires = datetime.utcnow() + timedelta(days=7)
    response = client.post(
        "/api/v1/allowlist/",
        json={
            "resource_id": "cluster-2",
            "resource_type": "cluster",
            "workspace": "prod-analytics",
            "justification": "Temporary.",
            "expires_at": expires.isoformat(),
        },
    )
    assert response.status_code == 200
    assert response.json()["expires_at"] is not None


def test_deleting_something_that_is_not_there_is_a_404(client):
    assert client.delete("/api/v1/allowlist/999999").status_code == 404


def test_entries_created_directly_are_visible_through_the_api(client, db_session):
    """The factory and the API agree about the same table."""
    row = AllowlistFactory.create(db_session, resource_id="warehouse-9")
    listed = client.get("/api/v1/allowlist/").json()
    assert any(e["id"] == row.id for e in listed)
