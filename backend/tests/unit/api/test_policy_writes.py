"""Policies change by pull request, and by nothing else.

The point of these tests is structural rather than behavioural. Anyone can add
an endpoint that writes a policy to disk and it will work on their laptop; it
will also quietly discard the user's edit the first time the deployed container
restarts. So the suite asserts the *absence* of those paths as much as the
presence of the pull request one.
"""
from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.api.v1.endpoints import policies as policies_endpoint
from app.core.config import settings


# --- The write paths that must not come back --------------------------------


def test_there_is_no_endpoint_that_writes_a_policy_to_disk():
    """A POST to /policies/{name} used to save the file. It cannot come back."""
    writes = {
        (method, route.path)
        for route in policies_endpoint.router.routes
        for method in route.methods
        if method in {"POST", "PUT", "PATCH"} and route.path == "/{policy_name}"
    }
    assert writes == set(), (
        "Policies are stored in git. A direct write endpoint produces an edit "
        "that survives until the next restart and then disappears."
    )


def test_the_explain_endpoint_no_longer_writes_a_file():
    from app.api.v1.endpoints import agent

    assert not hasattr(agent.ExplainRequest, "model_fields") or (
        "write" not in agent.ExplainRequest.model_fields
    )


def test_nothing_generates_and_writes_an_explanation():
    from app.agents import explain_rego

    assert not hasattr(explain_rego, "write_explanation")


# --- The pull request path --------------------------------------------------


@pytest.fixture
def github(monkeypatch):
    """A GitHub that records every write it is asked to make."""
    calls: list[dict] = []
    existing = {"backend/policies/clusters.rego": "package clusters\n"}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else {}

        if path.endswith("/git/refs/heads/main"):
            return httpx.Response(200, json={"object": {"sha": "base-sha"}})

        if path.endswith("/git/refs") and request.method == "POST":
            calls.append({"op": "branch", "ref": body["ref"]})
            return httpx.Response(201, json={"ref": body["ref"]})

        if "/contents/" in path:
            repo_path = path.split("/contents/", 1)[1]
            if request.method == "GET":
                if repo_path not in existing:
                    return httpx.Response(404, json={"message": "not found"})
                return httpx.Response(
                    200,
                    json={
                        "sha": f"sha-{repo_path}",
                        "content": base64.b64encode(
                            existing[repo_path].encode()
                        ).decode(),
                    },
                )
            if request.method == "PUT":
                calls.append({"op": "commit", "path": repo_path, "body": body})
                return httpx.Response(201, json={"content": {"sha": "new"}})
            if request.method == "DELETE":
                calls.append({"op": "delete", "path": repo_path})
                return httpx.Response(200, json={"commit": {"sha": "new"}})

        if path.endswith("/pulls"):
            calls.append({"op": "pr", "body": body})
            return httpx.Response(
                201, json={"html_url": "https://github.com/acme/governance/pull/7"}
            )

        return httpx.Response(404, json={"message": f"unhandled {path}"})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(settings, "GITHUB_REPO", "acme/governance")
    monkeypatch.setattr(settings, "GITHUB_TARGET_BRANCH", "main")
    monkeypatch.setattr(settings, "GITHUB_POLICIES_DIR", "backend/policies")
    monkeypatch.setattr(
        policies_endpoint,
        "get_github_client",
        lambda: httpx.AsyncClient(
            transport=transport, base_url="https://api.github.com"
        ),
    )
    return calls


@pytest.fixture
def stub_agent(monkeypatch):
    """The assistant, stubbed. Its availability is not what these tests are about."""
    async def fake_explain(policy_name, content, **kwargs):
        return f"This policy warns the owner of every cluster in {policy_name}."

    async def fake_notes(policy_name, new_content, old_content="", **kwargs):
        return {"body": "Generated notes.", "escalations": []}

    monkeypatch.setattr("app.agents.explain_rego.explain_rego", fake_explain)
    monkeypatch.setattr("app.agents.pr_notes.pr_notes", fake_notes)


def test_a_policy_change_commits_the_rego_and_its_english_together(
    client, github, stub_agent
):
    """A reviewer who cannot read Rego still sees the consequence change."""
    response = client.post(
        "/api/v1/policies/clusters.rego/pr",
        json={"content": "package clusters\n# revised\n"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["explanation_committed"] is True

    committed = {c["path"] for c in github if c["op"] == "commit"}
    assert committed == {
        "backend/policies/clusters.rego",
        "backend/policies/clusters.md",
    }


def test_both_files_land_on_the_same_branch(client, github, stub_agent):
    """Two commits on separate branches would put the English in a different PR."""
    client.post(
        "/api/v1/policies/clusters.rego/pr",
        json={"content": "package clusters\n# revised\n"},
    )

    branches = {c["body"]["branch"] for c in github if c["op"] == "commit"}
    pr = next(c for c in github if c["op"] == "pr")

    assert len(branches) == 1
    assert pr["body"]["head"] == branches.pop()


def test_a_failed_explanation_does_not_block_the_policy_change(
    client, github, monkeypatch
):
    """The assistant being down must not cost the user their edit."""
    async def boom(*args, **kwargs):
        raise RuntimeError("the gateway is unreachable")

    async def fake_notes(*args, **kwargs):
        return {"body": "Generated notes.", "escalations": []}

    monkeypatch.setattr("app.agents.explain_rego.explain_rego", boom)
    monkeypatch.setattr("app.agents.pr_notes.pr_notes", fake_notes)

    response = client.post(
        "/api/v1/policies/clusters.rego/pr",
        json={"content": "package clusters\n# revised\n"},
    )

    assert response.status_code == 200
    assert response.json()["explanation_committed"] is False
    committed = {c["path"] for c in github if c["op"] == "commit"}
    assert committed == {"backend/policies/clusters.rego"}


def test_a_tier_escalation_is_flagged_in_the_pull_request_title(
    client, github, monkeypatch
):
    """The reviewer's list view shows the title and nothing else."""
    async def fake_explain(*args, **kwargs):
        return "Explanation."

    async def escalating_notes(*args, **kwargs):
        return {"body": "Notes.", "escalations": ["cluster_idle: WARN -> REVOKE_ACCESS"]}

    monkeypatch.setattr("app.agents.explain_rego.explain_rego", fake_explain)
    monkeypatch.setattr("app.agents.pr_notes.pr_notes", escalating_notes)

    client.post(
        "/api/v1/policies/clusters.rego/pr",
        json={"content": "package clusters\n"},
    )

    pr = next(c for c in github if c["op"] == "pr")
    assert pr["body"]["title"].startswith("[TIER ESCALATION]")


def test_retiring_a_policy_goes_through_review_too(client, github):
    """Retiring stops a policy enforcing everywhere, which is a bigger change than most edits."""
    response = client.delete("/api/v1/policies/clusters.rego")

    assert response.status_code == 200
    assert "pull/7" in response.json()["pr_url"]

    deleted = {c["path"] for c in github if c["op"] == "delete"}
    assert "backend/policies/clusters.rego" in deleted


def test_retiring_a_policy_that_is_not_in_git_is_a_404(client, github):
    response = client.delete("/api/v1/policies/nonexistent.rego")
    assert response.status_code == 404


def test_editing_without_github_configured_explains_why(client, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_TOKEN", None)

    response = client.post(
        "/api/v1/policies/clusters.rego/pr", json={"content": "package clusters\n"}
    )

    assert response.status_code == 400
    assert "git" in response.json()["detail"].lower()
