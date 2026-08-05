"""Response shapes the frontend reads by name.

`src/services/api.ts` declares the shape of every response with a TypeScript
generic. Nothing validates that claim at runtime, so when an endpoint's payload
changes the client keeps compiling and fails in the browser instead — which is
how `result.run_ids.length` survived long enough to reach a user as "Cannot read
properties of undefined".

These tests pin the keys the UI actually dereferences. They are deliberately
about presence rather than values: a renamed or dropped key is the failure mode,
and it is one the typechecker cannot see.

When you change a payload here, change `src/services/api.ts` in the same commit.
"""
import pytest

from tests.factories import SentinelFindingFactory, SentinelRunFactory


def assert_keys(payload: dict, *expected: str) -> None:
    missing = [key for key in expected if key not in payload]
    assert not missing, (
        f"Response is missing {missing}, which src/services/api.ts declares. "
        f"Present: {sorted(payload)}"
    )


@pytest.fixture
def run(db_session):
    return SentinelRunFactory.create(db_session)


@pytest.fixture
def stub_scan(monkeypatch):
    """Stop the trigger endpoint actually scanning.

    TestClient runs background tasks once the response is returned, so without
    this the contract tests reach for real workspace credentials and take half a
    minute each. The response is built before the task is queued, so stubbing
    the scan does not weaken what these assert.
    """
    from app.api.v1.endpoints import sentinel as endpoint

    async def _noop(workspaces, *, mode, run_id=None, approval=None):
        return {"status": "completed", "workspaces": [], "mode": mode.value}

    monkeypatch.setattr(endpoint, "scan_workspaces", _noop)


@pytest.fixture
def workspaces(monkeypatch):
    from app.core.config import settings

    def _set(*names: str):
        monkeypatch.setattr(
            type(settings),
            "get_workspaces",
            lambda self: [{"name": n, "environment": "prod"} for n in names],
        )

    return _set


# --- Triggering a scan ------------------------------------------------------


def test_triggering_a_run_returns_what_the_toast_reads(client, stub_scan, workspaces):
    """The regression: the client read `run_ids`, the server sent `run_id`."""
    workspaces("prod")

    body = client.post("/api/v1/sentinel/run", json={"mode": "audit"}).json()

    assert_keys(body, "message", "run_id", "mode", "workspaces")
    assert isinstance(body["run_id"], str), "one id covers every workspace in the run"
    assert body["workspaces"] == ["prod"]


def test_a_run_id_is_a_single_string_not_a_list(client, stub_scan, workspaces):
    """Every workspace in one scan shares a run id. If that ever becomes a list,
    the dashboard's totals stop adding up and this should fail loudly."""
    workspaces("prod", "staging")

    body = client.post("/api/v1/sentinel/run", json={"mode": "audit"}).json()

    assert isinstance(body["run_id"], str)
    assert sorted(body["workspaces"]) == ["prod", "staging"]


def test_an_unmatched_workspace_filter_is_refused(client, stub_scan, workspaces):
    """Rather than silently scanning everything, or nothing."""
    workspaces("prod")

    response = client.post(
        "/api/v1/sentinel/run", json={"mode": "audit", "workspaces": ["nope"]}
    )
    assert response.status_code == 400


def test_enforce_mode_without_an_approval_is_refused_not_downgraded(client, stub_scan):
    """The operator asked for something specific and must be told they did not
    get it."""
    response = client.post("/api/v1/sentinel/run", json={"mode": "enforce"})

    assert response.status_code == 400
    assert "approval" in response.json()["detail"].lower()


# --- Listing and detail -----------------------------------------------------


def test_the_runs_page_shape(client, run):
    body = client.get("/api/v1/sentinel/runs").json()
    assert_keys(body, "total", "skip", "limit", "runs")

    assert_keys(
        body["runs"][0],
        "id",
        "workspace",
        "environment",
        "mode",
        "status",
        "started_at",
        "violation_count",
        "check_count",
        "remediated_count",
        "downgraded_count",
    )


def test_the_findings_page_shape(client, db_session, run):
    SentinelFindingFactory.create(db_session, run.id)

    body = client.get(f"/api/v1/sentinel/runs/{run.id}/findings").json()
    assert_keys(body, "total", "skip", "limit", "findings")

    assert_keys(
        body["findings"][0],
        "id",
        "kind",
        "resource_id",
        "resource_type",
        "resource_name",
        "owner",
        "policy",
        "rule_id",
        "policy_id",
        "category",
        "severity",
        "message",
        "requested_action",
        "effective_action",
        "tier",
        "requested_tier",
        "downgrade_reason",
        "executed",
    )


def test_the_facets_shape(client, db_session, run):
    SentinelFindingFactory.create(db_session, run.id)

    body = client.get(f"/api/v1/sentinel/runs/{run.id}/facets").json()
    assert_keys(
        body,
        "severity",
        "category",
        "resource_type",
        "policy",
        "policy_id",
        "effective_action",
    )
    assert_keys(body["severity"][0], "value", "count")


def test_the_audit_page_shape(client, db_session, run):
    from tests.factories import EnforcementAuditFactory

    EnforcementAuditFactory.create(db_session, run_id=run.id)

    body = client.get("/api/v1/sentinel/audit").json()
    assert_keys(body, "total", "entries")
    # Every field ActionsTakenPanel dereferences.
    assert_keys(
        body["entries"][0],
        "id",
        "run_id",
        "workspace",
        "resource_id",
        "resource_type",
        "requested_action",
        "effective_action",
        "downgrade_reason",
        "tier",
        "outcome",
        "error",
        "started_at",
        "undone_at",
        "undoable",
    )


# --- Agent ------------------------------------------------------------------


def test_the_agent_status_shape(client):
    """The chat panel disables itself based on these."""
    body = client.get("/api/v1/agent/status").json()
    assert_keys(
        body,
        "enabled",
        "configured",
        "model",
        "via_gateway",
        "tools",
        "max_generated_tier",
    )


# --- Releases and settings --------------------------------------------------


def test_the_settings_schema_shape(client):
    body = client.get("/api/v1/settings").json()
    assert_keys(body, "groups", "enforcement_enabled", "destructive_workspaces")

    group = body["groups"][0]
    assert_keys(group, "name", "danger", "fields")
    assert_keys(group["fields"][0], "key", "label", "type", "value", "overridden")


def test_the_settings_schema_exposes_the_banner_fields(client):
    """EnforcementBanner reads these two off the top level, not out of a group."""
    body = client.get("/api/v1/settings").json()

    assert isinstance(body["enforcement_enabled"], bool)
    assert isinstance(body["destructive_workspaces"], list)
