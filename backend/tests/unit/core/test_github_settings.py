"""GitHub configuration in the admin settings.

The token is the first real secret to become editable here, so most of these are
about it not coming back out. The rest are about the repository and branch being
treated as what they are: the answer to "which rules govern this estate".
"""
from __future__ import annotations

import json

import pytest

from app.core import settings_store
from app.core.config import settings


TOKEN = "ghp_exampletokenvalue0123456789"


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_TOKEN", None)
    monkeypatch.setattr(settings, "GITHUB_REPO", None)


# --- The secret stays on the server -----------------------------------------


def test_the_token_is_never_in_the_settings_response(client, db_session):
    """It would otherwise sit in every admin's browser and network log."""
    settings_store.set_override(db_session, "GITHUB_TOKEN", TOKEN)
    db_session.commit()

    body = client.get("/api/v1/settings").text

    assert TOKEN not in body
    assert "exampletokenvalue" not in body


def test_the_token_field_says_what_is_in_place_without_saying_what_it_is(
    client, db_session
):
    settings_store.set_override(db_session, "GITHUB_TOKEN", TOKEN)
    db_session.commit()

    groups = client.get("/api/v1/settings").json()["groups"]
    field = next(
        f
        for g in groups
        for f in g["fields"]
        if f["key"] == "GITHUB_TOKEN"
    )

    assert field["value"] is None
    assert field["configured"] is True
    assert field["hint"].endswith("6789")
    assert TOKEN not in json.dumps(field)


def test_an_absent_token_reports_itself_as_unconfigured(client):
    groups = client.get("/api/v1/settings").json()["groups"]
    field = next(
        f for g in groups for f in g["fields"] if f["key"] == "GITHUB_TOKEN"
    )

    assert field["configured"] is False
    assert field["hint"] is None


def test_writing_the_token_does_not_echo_it_back(client):
    response = client.put(
        "/api/v1/settings/GITHUB_TOKEN", json={"value": TOKEN}
    )

    assert response.status_code == 200
    assert TOKEN not in response.text
    assert response.json()["value"] is None


def test_a_bulk_write_does_not_echo_it_back(client):
    response = client.put(
        "/api/v1/settings",
        json={"values": {"GITHUB_TOKEN": TOKEN, "GITHUB_TARGET_BRANCH": "main"}},
    )

    assert TOKEN not in response.text
    assert response.json()["applied"]["GITHUB_TOKEN"] is None
    # Non-secrets still report what they were set to.
    assert response.json()["applied"]["GITHUB_TARGET_BRANCH"] == "main"


def test_the_token_is_masked_in_the_log(client, caplog):
    with caplog.at_level("INFO"):
        client.put("/api/v1/settings/GITHUB_TOKEN", json={"value": TOKEN})

    assert TOKEN not in caplog.text


def test_the_token_still_reaches_the_code_that_needs_it(client, db_session):
    """Masking is for the way out; the value itself has to be usable."""
    settings_store.set_override(db_session, "GITHUB_TOKEN", TOKEN)

    assert settings.GITHUB_TOKEN == TOKEN


# --- The repository is a safety setting -------------------------------------


def test_the_repository_and_branch_are_danger_settings():
    """They decide which rules run against real resources. Pointed elsewhere,
    the next sync replaces every policy with another repository's."""
    assert "GITHUB_REPO" in settings_store.DANGER_KEYS
    assert "GITHUB_TARGET_BRANCH" in settings_store.DANGER_KEYS
    assert "GITHUB_POLICIES_DIR" in settings_store.DANGER_KEYS


@pytest.mark.parametrize(
    "value",
    [
        "not-a-pair",
        "too/many/parts",
        "https://github.com/owner/name",
        "github.com/owner/name",
        "owner/",
        "/name",
    ],
)
def test_a_malformed_repository_is_refused(client, value):
    """A wrong repository reads as a 404 from GitHub, which looks like a
    permissions problem rather than a typo."""
    response = client.put("/api/v1/settings/GITHUB_REPO", json={"value": value})

    assert response.status_code == 400


def test_a_well_formed_repository_is_accepted(client):
    response = client.put(
        "/api/v1/settings/GITHUB_REPO",
        json={"value": "databricks-field-eng/policy-enforcement-sentinel"},
    )

    assert response.status_code == 200
    assert settings.GITHUB_REPO == "databricks-field-eng/policy-enforcement-sentinel"


def test_clearing_the_repository_is_allowed(client):
    """Blank turns the integration off, which has to remain reachable."""
    response = client.put("/api/v1/settings/GITHUB_REPO", json={"value": ""})

    assert response.status_code == 200


def test_configuring_github_here_takes_effect_without_a_restart(client, db_session):
    """The client is built per request, so an override applies immediately.

    A settings page that appears to change something it cannot is the one thing
    this store is not allowed to do.
    """
    from app.api.v1.endpoints.policies import get_github_client

    assert get_github_client() is None

    settings_store.set_override(db_session, "GITHUB_TOKEN", TOKEN)
    settings_store.set_override(db_session, "GITHUB_REPO", "owner/name")
    db_session.commit()

    client_instance = get_github_client()
    assert client_instance is not None
    assert client_instance.headers["Authorization"] == f"Bearer {TOKEN}"

    assert client.get("/api/v1/policies/config").json()["github_enabled"] is True
