"""The working copy is rebuilt from git, and nothing else writes to it.

These tests exist because the failure they guard against is invisible in
development. A local checkout has a durable filesystem, so writing policies to
disk works perfectly right up until the app is deployed onto an ephemeral one,
where the same code silently loses every edit at the next restart.
"""
from __future__ import annotations

import base64
import os

import httpx
import pytest

from app.core.config import settings
from app.services import policy_sync


@pytest.fixture
def working_copy(tmp_path, monkeypatch):
    """An empty policies directory that is not a git checkout."""
    policies = tmp_path / "policies"
    policies.mkdir()

    monkeypatch.setattr(type(settings), "get_policies_dir", property(lambda _: str(policies)))
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(settings, "GITHUB_REPO", "acme/governance")
    monkeypatch.setattr(settings, "GITHUB_TARGET_BRANCH", "main")
    monkeypatch.setattr(settings, "GITHUB_POLICIES_DIR", "backend/policies")
    monkeypatch.setattr(policy_sync, "is_local_checkout", lambda *a, **k: False)
    return policies


def fake_github(files: dict[str, str]) -> httpx.MockTransport:
    """A GitHub that serves exactly ``files`` from the policies directory."""
    blobs = {f"sha-{name}": content for name, content in files.items()}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/contents/backend/policies"):
            return httpx.Response(
                200,
                json=[
                    {"name": name, "type": "file", "sha": f"sha-{name}"}
                    for name in files
                ],
            )
        if "/git/blobs/" in path:
            sha = path.rsplit("/", 1)[-1]
            return httpx.Response(
                200,
                json={
                    "encoding": "base64",
                    "content": base64.b64encode(blobs[sha].encode()).decode(),
                },
            )
        return httpx.Response(404, json={"message": "not found"})

    return httpx.MockTransport(handler)


def use_transport(monkeypatch, transport: httpx.MockTransport) -> None:
    monkeypatch.setattr(
        policy_sync,
        "_client",
        lambda: httpx.AsyncClient(transport=transport, base_url="https://api.github.com"),
    )


@pytest.mark.asyncio
async def test_the_working_copy_is_populated_from_the_target_branch(
    working_copy, monkeypatch
):
    use_transport(
        monkeypatch,
        fake_github({"clusters.rego": "package clusters\n", "clusters.md": "# Clusters\n"}),
    )

    result = await policy_sync.sync_policies()

    assert result.status == "ok"
    assert sorted(result.written) == ["clusters.md", "clusters.rego"]
    assert (working_copy / "clusters.rego").read_text() == "package clusters\n"
    assert (working_copy / "clusters.md").read_text() == "# Clusters\n"


@pytest.mark.asyncio
async def test_a_policy_removed_from_git_stops_being_evaluated(
    working_copy, monkeypatch
):
    """A retired policy that lingers on disk keeps enforcing after its PR merged."""
    (working_copy / "retired.rego").write_text("package retired\n")
    use_transport(monkeypatch, fake_github({"clusters.rego": "package clusters\n"}))

    result = await policy_sync.sync_policies()

    assert result.removed == ["retired.rego"]
    assert not (working_copy / "retired.rego").exists()


@pytest.mark.asyncio
async def test_unchanged_files_are_not_rewritten(working_copy, monkeypatch):
    """OPA watches this directory; rewriting identical bytes reloads it for nothing."""
    use_transport(monkeypatch, fake_github({"clusters.rego": "package clusters\n"}))

    await policy_sync.sync_policies()
    before = os.stat(working_copy / "clusters.rego").st_mtime_ns

    second = await policy_sync.sync_policies()

    assert second.written == []
    assert os.stat(working_copy / "clusters.rego").st_mtime_ns == before


@pytest.mark.asyncio
async def test_a_failed_sync_leaves_the_previous_copy_in_place(
    working_copy, monkeypatch
):
    """Stale policies still enforce something. An empty directory passes everything."""
    use_transport(monkeypatch, fake_github({"clusters.rego": "package clusters\n"}))
    await policy_sync.sync_policies()

    def explode(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "GitHub is having a day"})

    use_transport(monkeypatch, httpx.MockTransport(explode))
    result = await policy_sync.sync_policies()

    assert result.status == "failed"
    assert (working_copy / "clusters.rego").read_text() == "package clusters\n"


@pytest.mark.asyncio
async def test_a_local_checkout_is_never_clobbered(working_copy, monkeypatch):
    """In development the checkout *is* the working copy; syncing would eat uncommitted work."""
    (working_copy / "clusters.rego").write_text("package clusters\n# work in progress\n")
    monkeypatch.setattr(policy_sync, "is_local_checkout", lambda *a, **k: True)
    use_transport(monkeypatch, fake_github({"clusters.rego": "package clusters\n"}))

    result = await policy_sync.sync_policies()

    assert result.status == "local"
    assert "work in progress" in (working_copy / "clusters.rego").read_text()


@pytest.mark.asyncio
async def test_sync_is_skipped_when_github_is_not_configured(working_copy, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_TOKEN", None)

    result = await policy_sync.sync_policies()

    assert result.status == "disabled"


@pytest.mark.asyncio
async def test_only_rego_and_markdown_come_down(working_copy, monkeypatch):
    """The directory is an OPA bundle; a stray file type is at best ignored."""
    use_transport(
        monkeypatch,
        fake_github(
            {
                "clusters.rego": "package clusters\n",
                "notes.txt": "scratch",
                "secrets.env": "TOKEN=hunter2",
            }
        ),
    )

    await policy_sync.sync_policies()

    assert sorted(os.listdir(working_copy)) == ["clusters.rego"]
