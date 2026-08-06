"""The fences around a pattern exception.

Rego refuses to match a pattern with a missing selector, and that is the
guarantee that matters — it is enforced where the decision is made. These tests
cover the second fence, which stops such a row from being written at all, plus
the compulsory expiry, which Rego has no way to require.

Two fences rather than one because they fail differently. A row rejected here
tells someone what they got wrong while they are still looking at the form; a
row that got through and is ignored by Rego is a waiver someone believes they
have and does not.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

FUTURE = (datetime.utcnow() + timedelta(days=30)).isoformat()
PAST = (datetime.utcnow() - timedelta(days=1)).isoformat()


def pattern(**overrides) -> dict:
    body = {
        "match_type": "pattern",
        "resource_type": "cluster",
        "rule_id": "CST-CLU-005",
        "workspace": "prod-analytics",
        "justification": "Agreed with the platform team for the migration.",
        "expires_at": FUTURE,
    }
    body.update(overrides)
    return {k: v for k, v in body.items() if v is not _OMIT}


_OMIT = object()


def resource(**overrides) -> dict:
    body = {
        "match_type": "resource",
        "resource_id": "cluster-abc",
        "resource_type": "cluster",
        "workspace": "prod-analytics",
        "justification": "Owned by the data platform team.",
    }
    body.update(overrides)
    return {k: v for k, v in body.items() if v is not _OMIT}


# --- The older shape is untouched -------------------------------------------


def test_a_resource_exception_still_works_without_a_match_type(client):
    body = resource()
    del body["match_type"]

    response = client.post("/api/v1/allowlist", json=body)

    assert response.status_code == 200
    assert response.json()["match_type"] == "resource"


def test_a_resource_exception_may_be_permanent(client):
    """Unchanged: one named resource somebody had to go and find."""
    response = client.post("/api/v1/allowlist", json=resource())

    assert response.status_code == 200
    assert response.json()["expires_at"] is None


# --- Patterns need both selectors -------------------------------------------


@pytest.mark.parametrize("missing", ["rule_id", "resource_type"])
def test_a_pattern_without_both_selectors_is_refused(client, missing):
    response = client.post("/api/v1/allowlist", json=pattern(**{missing: _OMIT}))

    assert response.status_code == 422


@pytest.mark.parametrize("blank", ["", "   "])
@pytest.mark.parametrize("field", ["rule_id", "resource_type"])
def test_a_blank_selector_is_refused(client, field, blank):
    """Empty is never a wildcard, and never reaches the database as one."""
    response = client.post("/api/v1/allowlist", json=pattern(**{field: blank}))

    assert response.status_code == 422


def test_a_pattern_may_not_also_name_a_resource(client):
    """The two shapes are alternatives; a row that is both is a row nobody can
    reason about."""
    response = client.post("/api/v1/allowlist", json=pattern(resource_id="cluster-abc"))

    assert response.status_code == 422


def test_a_resource_exception_may_not_carry_a_rule_id(client):
    """It waives every failing rule, so a rule ID on it would be a lie."""
    response = client.post("/api/v1/allowlist", json=resource(rule_id="CST-CLU-005"))

    assert response.status_code == 422


def test_an_unknown_match_type_is_refused(client):
    response = client.post("/api/v1/allowlist", json=pattern(match_type="everything"))

    assert response.status_code == 422


# --- Patterns must expire ---------------------------------------------------


def test_a_pattern_without_an_expiry_is_refused(client):
    """A permanent class-wide waiver is a policy change with no pull request."""
    response = client.post("/api/v1/allowlist", json=pattern(expires_at=None))

    assert response.status_code == 422
    assert "expire" in response.text.lower()


def test_a_pattern_expiring_in_the_past_is_refused(client):
    response = client.post("/api/v1/allowlist", json=pattern(expires_at=PAST))

    assert response.status_code == 422


def test_a_pattern_expiry_cannot_be_cleared_by_editing(client):
    """Editing is the obvious way round a rule enforced only on the way in."""
    created = client.post("/api/v1/allowlist", json=pattern()).json()

    response = client.patch(
        f"/api/v1/allowlist/{created['id']}", json={"expires_at": None}
    )

    assert response.status_code == 422
    assert client.get("/api/v1/allowlist").json()[0]["expires_at"] is not None


def test_a_resource_expiry_may_still_be_cleared(client):
    """The restriction is about breadth, not about expiry in general."""
    created = client.post(
        "/api/v1/allowlist", json=resource(expires_at=FUTURE)
    ).json()

    response = client.patch(
        f"/api/v1/allowlist/{created['id']}", json={"expires_at": None}
    )

    assert response.status_code == 200
    assert response.json()["expires_at"] is None


# --- Round trip -------------------------------------------------------------


def test_a_valid_pattern_is_stored_and_returned(client):
    response = client.post(
        "/api/v1/allowlist", json=pattern(created_by="sam@company.com")
    )

    assert response.status_code == 200
    body = response.json()
    assert body["match_type"] == "pattern"
    assert body["rule_id"] == "CST-CLU-005"
    assert body["resource_id"] is None
    assert body["created_by"] == "sam@company.com"


def test_the_list_reports_the_match_type_for_every_row(client):
    """The page groups by it, so it cannot be absent."""
    client.post("/api/v1/allowlist", json=resource())
    client.post("/api/v1/allowlist", json=pattern())

    rows = client.get("/api/v1/allowlist").json()

    assert sorted(row["match_type"] for row in rows) == ["pattern", "resource"]
