"""Config helpers, mostly on their malformed inputs.

Every function here parses something a human typed into a settings field or an
environment variable. The interesting case in each is the one where they typed
it wrong, because the alternative to handling that is a backend that will not
start.
"""
import json

import pytest

from app.core.config import Settings


@pytest.fixture
def config():
    return Settings()


# --- Workspaces -------------------------------------------------------------


def test_workspaces_are_read_from_json(config):
    config.SENTINEL_WORKSPACES = json.dumps(
        [
            {"name": "prod", "environment": "prod"},
            {"name": "staging", "environment": "staging"},
        ]
    )

    assert [w["name"] for w in config.get_workspaces()] == ["prod", "staging"]


def test_malformed_workspace_json_falls_back_rather_than_crashing(config, caplog):
    """A typo in this field must not take the backend down on boot."""
    config.SENTINEL_WORKSPACES = "{not json"
    config.SENTINEL_CRON_WORKSPACE = "fallback-ws"

    with caplog.at_level("ERROR"):
        workspaces = config.get_workspaces()

    assert [w["name"] for w in workspaces] == ["fallback-ws"]
    assert any("SENTINEL_WORKSPACES" in r.message for r in caplog.records)


def test_the_legacy_single_workspace_variables_still_work(config):
    """Deployments configured before multi-workspace existed keep scanning."""
    config.SENTINEL_WORKSPACES = ""
    config.SENTINEL_CRON_WORKSPACE = "ws-enterprise-prod"
    config.SENTINEL_CRON_ENV = "prod"
    config.DATABRICKS_HOST = "https://example.databricks.com"

    workspace = config.get_workspaces()[0]

    assert workspace["name"] == "ws-enterprise-prod"
    assert workspace["environment"] == "prod"
    assert workspace["host"] == "https://example.databricks.com"


# --- The destructive workspace allowlist ------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("", []),
        ("   ", []),
        ("prod", ["prod"]),
        ("prod,staging", ["prod", "staging"]),
        ("prod, staging ,  dev ", ["prod", "staging", "dev"]),
        (",,prod,,", ["prod"]),
    ],
)
def test_the_destructive_allowlist_parses_forgivingly(config, raw, expected):
    """Whitespace and stray commas are how people type lists. None of those
    variations should widen or narrow the allowlist unexpectedly."""
    config.DESTRUCTIVE_ACTION_WORKSPACES = raw
    assert config.destructive_workspaces() == expected


def test_an_empty_allowlist_permits_nothing(config):
    """The shipped value. It has to mean "no workspace", never "any"."""
    config.DESTRUCTIVE_ACTION_WORKSPACES = ""
    assert config.destructive_workspaces() == []


# --- OPA --------------------------------------------------------------------


def test_an_explicit_opa_url_wins_over_the_embedded_server(config):
    config.OPA_URL = "http://opa.internal:8181"
    assert config.opa_provider_config()["opa_url"] == "http://opa.internal:8181"


def test_the_provider_config_always_names_the_policies_directory(config):
    assert config.opa_provider_config()["policies_dir"] == config.get_policies_dir
