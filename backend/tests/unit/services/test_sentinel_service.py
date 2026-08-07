"""The scan engine, driven through fake boundaries.

Every external edge — the Databricks client, the handlers, OPA — is replaced
with an in-process fake. That buys the thing that matters most about this file:
the failure paths are exercisable. A workspace we cannot authenticate to, a
resource type we cannot enumerate, and an OPA process that dies mid-run are all
states the real system reaches regularly and none of them are reachable in a
test that talks to a live workspace.

The recurring assertion is that a scan which could not see something says so.
Silence in a compliance tool reads as "clean", and that is the one wrong answer
this system must never give.
"""
from __future__ import annotations

import pytest

from app.core.enforcement import ScanMode
from app.db.sentinel_finding import SentinelFindingModel
from app.providers.databricks.handlers.base import BaseResourceHandler
from app.services import sentinel_service
from app.services.sentinel_service import SentinelService


class FakeCurrentUser:
    def __init__(self, fail: bool = False):
        self._fail = fail

    def me(self):
        if self._fail:
            raise PermissionError("token expired")
        return type("User", (), {"user_name": "svc@company.com"})()


class FakeWorkspaceClient:
    def __init__(self, auth_fails: bool = False):
        self.current_user = FakeCurrentUser(fail=auth_fails)


class FakeHandler(BaseResourceHandler):
    """Discover and warn, nothing more.

    Inheriting the base is what declares the ``warn`` capability — capabilities
    are nominal, not duck-typed, so a fake that merely defines a ``warn`` method
    would be refused by the chokepoint exactly as a real handler would be.
    """

    resource_type = "cluster"

    def __init__(self, client, resources=None, discover_error=None):
        self.client = client
        self._resources = resources or []
        self._discover_error = discover_error
        self.warned = []

    async def discover(self):
        if self._discover_error:
            raise self._discover_error
        return list(self._resources)

    async def warn(self, resource_id, message, owner=None):
        self.warned.append((resource_id, message))
        return {"success": True}


def handler_factory(resources=None, discover_error=None):
    def _make(client):
        return FakeHandler(client, resources=resources, discover_error=discover_error)

    return _make


@pytest.fixture
def scan_env(monkeypatch, app_db):
    """A service whose every boundary is a fake, plus knobs to configure them."""
    state = {
        "client": FakeWorkspaceClient(),
        "opa_results": {},
        "opa_error": None,
        "handlers": {},
    }

    service = SentinelService.__new__(SentinelService)
    service.workspace_config = {}

    class FakeProvider:
        @property
        def client(self):
            client = state["client"]
            if isinstance(client, Exception):
                raise client
            return client

    class FakeOpa:
        async def evaluate_namespace(self, input_data):
            if state["opa_error"]:
                raise state["opa_error"]
            results = state["opa_results"]
            return results(input_data) if callable(results) else results

    service.db_provider = FakeProvider()
    service.opa_provider = FakeOpa()

    monkeypatch.setattr(sentinel_service, "HANDLER_REGISTRY", state["handlers"])
    monkeypatch.setattr(SentinelService, "_load_allowlist", staticmethod(lambda ws: []))

    state["service"] = service
    return state


def findings_for(db_session, run_id):
    return (
        db_session.query(SentinelFindingModel)
        .filter(SentinelFindingModel.run_id == run_id)
        .all()
    )


# --- Failure is never silence ----------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_auth_probe_fails_the_run(scan_env, db_session):
    """Not "zero violations". A workspace we cannot read tells us nothing."""
    scan_env["client"] = FakeWorkspaceClient(auth_fails=True)

    summary = await scan_env["service"].scan_workspace("prod", "production", run_id="r1")

    assert summary["status"] == "failed"
    assert "auth" in summary["errors"]

    rows = findings_for(db_session, "r1")
    assert [r.kind for r in rows] == ["ws_failure"]
    assert "Authentication failed" in rows[0].message
    assert "No conclusions can be drawn" in rows[0].message


@pytest.mark.asyncio
async def test_a_client_that_cannot_be_built_fails_the_run(scan_env, db_session):
    scan_env["client"] = RuntimeError("no credentials configured")

    summary = await scan_env["service"].scan_workspace("prod", "production", run_id="r2")

    assert summary["status"] == "failed"
    rows = findings_for(db_session, "r2")
    assert rows and rows[0].kind == "ws_failure"


@pytest.mark.asyncio
async def test_a_resource_type_that_cannot_be_enumerated_marks_the_run_partial(
    scan_env, db_session
):
    """A handler that throws must not read as a resource type with nothing in it."""
    scan_env["handlers"]["cluster"] = handler_factory(
        discover_error=PermissionError("insufficient privileges")
    )

    summary = await scan_env["service"].scan_workspace("prod", "production", run_id="r3")

    assert summary["status"] == "partial"
    assert "cluster" in summary["errors"]

    rows = findings_for(db_session, "r3")
    failures = [r for r in rows if r.kind == "ws_failure"]
    assert len(failures) == 1
    assert "Could not enumerate cluster" in failures[0].message


@pytest.mark.asyncio
async def test_one_broken_resource_type_does_not_stop_the_others(scan_env, db_session):
    scan_env["handlers"]["cluster"] = handler_factory(
        discover_error=RuntimeError("boom")
    )
    scan_env["handlers"]["job"] = handler_factory(
        resources=[{"id": "j1", "name": "nightly", "type": "job"}]
    )
    scan_env["opa_results"] = {
        "jobs": {"applies": True, "rule_results": [{"rule": "r", "passed": True}]}
    }

    summary = await scan_env["service"].scan_workspace("prod", "production", run_id="r4")

    assert summary["status"] == "partial"
    assert summary["total_resources"] == 1
    assert summary["checks"] == 1


@pytest.mark.asyncio
async def test_an_opa_failure_is_recorded_not_treated_as_a_pass(scan_env, db_session):
    """The dangerous misreading: an evaluation that never ran looking compliant."""
    scan_env["handlers"]["cluster"] = handler_factory(
        resources=[{"id": "c1", "name": "analytics", "type": "cluster"}]
    )
    scan_env["opa_error"] = ConnectionError("OPA is not listening")

    summary = await scan_env["service"].scan_workspace("prod", "production", run_id="r5")

    rows = findings_for(db_session, "r5")
    assert [r.kind for r in rows] == ["ws_failure"]
    assert summary["checks"] == 0
    assert summary["remediated"] == 0
    assert summary["status"] == "partial"


# --- Verdicts ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_passing_rules_are_recorded_as_checks(scan_env, db_session):
    """"Checked and compliant" is a different fact from "never looked at"."""
    scan_env["handlers"]["cluster"] = handler_factory(
        resources=[{"id": "c1", "name": "analytics", "type": "cluster"}]
    )
    scan_env["opa_results"] = {
        "clusters": {
            "applies": True,
            "rule_results": [
                {"rule": "has_owner_tag", "passed": True, "severity": "MEDIUM"},
                {"rule": "autotermination_set", "passed": True, "severity": "LOW"},
            ],
        }
    }

    summary = await scan_env["service"].scan_workspace("prod", "production", run_id="r6")

    assert summary["checks"] == 2
    assert summary["violations"] == 0
    rows = findings_for(db_session, "r6")
    assert {r.rule_id for r in rows} == {"has_owner_tag", "autotermination_set"}


@pytest.mark.asyncio
async def test_a_policy_that_does_not_apply_produces_nothing(scan_env, db_session):
    scan_env["handlers"]["cluster"] = handler_factory(
        resources=[{"id": "c1", "name": "analytics", "type": "cluster"}]
    )
    scan_env["opa_results"] = {
        "jobs": {"applies": False, "rule_results": [{"rule": "r", "passed": False}]}
    }

    summary = await scan_env["service"].scan_workspace("prod", "production", run_id="r7")

    assert summary["checks"] == 0
    assert summary["violations"] == 0
    assert findings_for(db_session, "r7") == []


@pytest.mark.asyncio
async def test_a_violation_records_both_requested_and_effective_action(
    scan_env, db_session
):
    """The audit answers "what did the policy ask for" and "what happened"."""
    scan_env["handlers"]["cluster"] = handler_factory(
        resources=[{"id": "c1", "name": "analytics", "type": "cluster"}]
    )
    scan_env["opa_results"] = {
        "clusters": {
            "applies": True,
            "rule_results": [
                {
                    "rule": "missing_owner",
                    "passed": False,
                    "severity": "HIGH",
                    "messages": ["No owner tag."],
                    "requested_action": "WARN",
                }
            ],
        }
    }

    await scan_env["service"].scan_workspace(
        "prod", "production", mode=ScanMode.AUDIT, run_id="r8"
    )

    row = findings_for(db_session, "r8")[0]
    assert row.kind == "violation"
    assert row.requested_action == "WARN"
    # Audit mode records the finding and stops there: FLAG is Tier 0, the only
    # tier with no side effect at all.
    assert row.effective_action == "FLAG"
    assert row.downgrade_reason


@pytest.mark.asyncio
async def test_audit_mode_never_executes(scan_env, db_session):
    handler_holder = {}

    def _make(client):
        handler_holder["h"] = FakeHandler(
            client, resources=[{"id": "c1", "name": "a", "type": "cluster"}]
        )
        return handler_holder["h"]

    scan_env["handlers"]["cluster"] = _make
    scan_env["opa_results"] = {
        "clusters": {
            "applies": True,
            "rule_results": [
                {"rule": "r", "passed": False, "requested_action": "WARN", "messages": ["x"]}
            ],
        }
    }

    summary = await scan_env["service"].scan_workspace(
        "prod", "production", mode=ScanMode.AUDIT, run_id="r9"
    )

    assert summary["remediated"] == 0
    assert handler_holder["h"].warned == []


@pytest.mark.asyncio
async def test_remediate_mode_runs_the_tier_one_action(scan_env, db_session):
    handler_holder = {}

    def _make(client):
        handler_holder["h"] = FakeHandler(
            client, resources=[{"id": "c1", "name": "a", "type": "cluster"}]
        )
        return handler_holder["h"]

    scan_env["handlers"]["cluster"] = _make
    scan_env["opa_results"] = {
        "clusters": {
            "applies": True,
            "rule_results": [
                {
                    "rule": "r",
                    "passed": False,
                    "requested_action": "WARN",
                    "messages": ["No owner tag."],
                }
            ],
        }
    }

    summary = await scan_env["service"].scan_workspace(
        "prod", "production", mode=ScanMode.REMEDIATE, run_id="r10"
    )

    assert summary["remediated"] == 1
    assert handler_holder["h"].warned == [("c1", "No owner tag.")]


@pytest.mark.asyncio
async def test_a_destructive_request_is_downgraded_without_approval(
    scan_env, db_session
):
    """The end-to-end version of the chokepoint gates."""
    handler_holder = {}

    def _make(client):
        handler_holder["h"] = FakeHandler(
            client, resources=[{"id": "c1", "name": "a", "type": "cluster"}]
        )
        return handler_holder["h"]

    scan_env["handlers"]["cluster"] = _make
    scan_env["opa_results"] = {
        "clusters": {
            "applies": True,
            "rule_results": [
                {
                    "rule": "r",
                    "passed": False,
                    "requested_action": "TERMINATE",
                    "destructive": True,
                    "messages": ["Untagged cluster."],
                }
            ],
        }
    }

    summary = await scan_env["service"].scan_workspace(
        "prod", "production", mode=ScanMode.REMEDIATE, run_id="r11"
    )

    assert summary["downgraded"] == 1
    row = findings_for(db_session, "r11")[0]
    assert row.requested_action == "TERMINATE"
    assert row.effective_action != "TERMINATE"
    assert row.tier < row.requested_tier


@pytest.mark.asyncio
async def test_a_resource_with_no_handler_is_never_acted_on(scan_env, db_session):
    """Discovery and remediation are keyed independently; the gap must be safe."""
    scan_env["handlers"]["cluster"] = handler_factory(
        resources=[{"id": "x1", "name": "orphan", "type": "unregistered_type"}]
    )
    scan_env["opa_results"] = {
        "anything": {
            "applies": True,
            "rule_results": [
                {"rule": "r", "passed": False, "requested_action": "WARN", "messages": ["x"]}
            ],
        }
    }

    summary = await scan_env["service"].scan_workspace(
        "prod", "production", mode=ScanMode.REMEDIATE, run_id="r12"
    )

    assert summary["violations"] == 1
    assert summary["remediated"] == 0


# --- Scale ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_findings_are_written_in_batches(scan_env, db_session, monkeypatch):
    """Estates produce tens of thousands of findings; one INSERT each is fatal."""
    monkeypatch.setattr(sentinel_service, "FINDING_BATCH_SIZE", 100)
    resources = [
        {"id": f"c{i}", "name": f"cluster-{i}", "type": "cluster"} for i in range(250)
    ]
    scan_env["handlers"]["cluster"] = handler_factory(resources=resources)
    scan_env["opa_results"] = {
        "clusters": {"applies": True, "rule_results": [{"rule": "r", "passed": True}]}
    }

    commits = {"n": 0}
    real_commit = db_session.commit

    def counting_commit():
        commits["n"] += 1
        return real_commit()

    monkeypatch.setattr(db_session, "commit", counting_commit)

    summary = await scan_env["service"].scan_workspace(
        "prod", "production", run_id="r13"
    )

    assert summary["checks"] == 250
    assert commits["n"] == 3
    assert len(findings_for(db_session, "r13")) == 250


@pytest.mark.asyncio
async def test_concurrency_stays_within_the_configured_limit(scan_env, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "SENTINEL_SCAN_CONCURRENCY", 4)

    live = {"now": 0, "peak": 0}

    async def tracking_evaluate(input_data):
        import asyncio

        live["now"] += 1
        live["peak"] = max(live["peak"], live["now"])
        await asyncio.sleep(0)
        live["now"] -= 1
        return {"clusters": {"applies": True, "rule_results": [{"rule": "r", "passed": True}]}}

    scan_env["service"].opa_provider.evaluate_namespace = tracking_evaluate
    scan_env["handlers"]["cluster"] = handler_factory(
        resources=[{"id": f"c{i}", "name": f"c{i}", "type": "cluster"} for i in range(50)]
    )

    await scan_env["service"].scan_workspace("prod", "production", run_id="r14")

    assert live["peak"] <= 4


@pytest.mark.asyncio
async def test_one_workspace_failing_does_not_sink_the_others(monkeypatch, app_db):
    """Multi-workspace scans are concurrent; one bad tenant is not a scan failure."""

    async def fake_scan(self, workspace_name, environment, **kwargs):
        if workspace_name == "broken":
            raise ConnectionError("host unreachable")
        return {"workspace": workspace_name, "status": "completed", "violations": 0}

    monkeypatch.setattr(SentinelService, "scan_workspace", fake_scan)

    # `scan_workspaces` constructs a service per workspace before calling the
    # method above, and the constructor builds a real Databricks client. Faking
    # only `scan_workspace` left that constructor doing live OAuth against three
    # workspaces: with a token cached the suite ran in fifty seconds, and
    # without one it took fifteen minutes and then failed here on a five-minute
    # auth timeout that had nothing to do with what this test asserts.
    #
    # The other tests in this file dodge it with `__new__`. This one goes
    # through `scan_workspaces`, so the constructor is what has to be neutered.
    monkeypatch.setattr(SentinelService, "__init__", lambda self, config=None: None)

    results = await sentinel_service.scan_workspaces(
        [
            {"name": "good-1", "environment": "prod"},
            {"name": "broken", "environment": "prod"},
            {"name": "good-2", "environment": "prod"},
        ],
        mode=ScanMode.AUDIT,
    )

    by_workspace = {r["workspace"]: r for r in results["workspaces"]}
    assert by_workspace["good-1"]["status"] == "completed"
    assert by_workspace["good-2"]["status"] == "completed"
    assert by_workspace["broken"]["status"] == "failed"
