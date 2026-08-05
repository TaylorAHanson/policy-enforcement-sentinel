"""Discarding working-copy edits to a policy.

This is the only thing in the app that writes to the policies directory, so the
tests are mostly about what it refuses to do: touch anything outside that
directory, and touch anything that is not a policy.
"""
from __future__ import annotations

import subprocess

import pytest

from app.services import policy_history


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def checkout(tmp_path):
    """A real repository with one committed policy and one committed secret."""
    repo = tmp_path / "repo"
    policies = repo / "backend" / "policies"
    policies.mkdir(parents=True)

    _git("init", "-q", cwd=repo)
    _git("config", "user.email", "test@example.com", cwd=repo)
    _git("config", "user.name", "Test", cwd=repo)

    (policies / "clusters.rego").write_text("package committed\n")
    (repo / "secret.txt").write_text("committed secret\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "initial", cwd=repo)

    return repo, str(policies)


def test_an_edit_is_thrown_away(checkout):
    repo, policies = checkout
    target = repo / "backend" / "policies" / "clusters.rego"
    target.write_text("package edited_by_hand\n")

    assert policy_history.uncommitted_changes(policies, "clusters.rego") is True

    restored = policy_history.restore_from_head(policies, "clusters.rego")

    assert restored == "package committed\n"
    assert target.read_text() == "package committed\n"
    assert policy_history.uncommitted_changes(policies, "clusters.rego") is False


def test_a_staged_edit_is_thrown_away_too(checkout):
    """Restoring the file but leaving the staged copy would clear the warning
    while the difference was still there."""
    repo, policies = checkout
    target = repo / "backend" / "policies" / "clusters.rego"
    target.write_text("package staged\n")
    _git("add", "backend/policies/clusters.rego", cwd=repo)

    policy_history.restore_from_head(policies, "clusters.rego")

    assert target.read_text() == "package committed\n"
    assert policy_history.uncommitted_changes(policies, "clusters.rego") is False


def test_restoring_an_unchanged_policy_is_harmless(checkout):
    _repo, policies = checkout

    assert policy_history.restore_from_head(policies, "clusters.rego") == (
        "package committed\n"
    )


def test_it_cannot_reach_outside_the_policies_directory(checkout):
    """The name reaches a git pathspec, so traversal would restore any file in
    the repository — or, with a crafted name, act on one that is not a policy."""
    repo, policies = checkout
    secret = repo / "secret.txt"
    secret.write_text("edited secret\n")

    for name in (
        "../../secret.txt",
        "../../../etc/passwd",
        "/etc/passwd",
        "secret.txt",
        "clusters.rego/../../../secret.txt",
    ):
        with pytest.raises(ValueError):
            policy_history.restore_from_head(policies, name)

    # Untouched: the edit above is still there.
    assert secret.read_text() == "edited secret\n"


def test_an_option_like_name_is_refused(checkout):
    """A leading dash would be read by git as a flag rather than a path."""
    _repo, policies = checkout

    with pytest.raises(ValueError):
        policy_history.restore_from_head(policies, "--force.rego")


def test_it_refuses_when_there_is_no_checkout(tmp_path):
    """The deployed case: the working copy is rebuilt by the sync instead, and
    a confident-looking failure here would be worse than an honest one."""
    policies = tmp_path / "policies"
    policies.mkdir()
    (policies / "clusters.rego").write_text("package x\n")

    with pytest.raises(policy_history.GitUnavailable):
        policy_history.restore_from_head(str(policies), "clusters.rego")


def test_only_the_named_policy_is_restored(checkout):
    """A blanket restore would silently take unrelated work with it."""
    repo, policies = checkout
    other = repo / "backend" / "policies" / "jobs.rego"
    other.write_text("package uncommitted_sibling\n")

    policy_history.restore_from_head(policies, "clusters.rego")

    assert other.read_text() == "package uncommitted_sibling\n"
