"""The explanation cache.

Two properties matter. One is that a hit is only ever an explanation of exactly
the content being asked about — the tab regenerates on its own now, so a cache
that could return a reading of a stale policy would be worse than no cache, and
worse than the button it replaced.

The other is that the cache never becomes a failure mode. It saves a model call;
losing it costs a model call. Nothing about it should be able to break the tab.
"""
from __future__ import annotations

import pytest

from app.agents.explain_rego import content_sha
from app.db.policy_explanation import PolicyExplanationModel
from app.services import explanation_cache

POLICY = """package databricks.governance.clusters

default applies := false
"""


# --- Keying -----------------------------------------------------------------


def test_the_same_content_hashes_the_same():
    assert content_sha(POLICY) == content_sha(POLICY)


def test_trailing_whitespace_is_not_a_different_policy():
    """A stray newline changes nothing about what the policy does."""
    assert content_sha(POLICY) == content_sha(f"{POLICY}\n\n  ")


def test_a_changed_rule_is_a_different_key():
    changed = POLICY.replace("false", "true")

    assert content_sha(POLICY) != content_sha(changed)


# --- Round trip -------------------------------------------------------------


def test_a_stored_explanation_comes_back(db_session, app_db):
    sha = content_sha(POLICY)
    explanation_cache.put(sha, "clusters.rego", "This warns the owner.")

    assert explanation_cache.get(sha) == "This warns the owner."


def test_a_miss_returns_none(db_session, app_db):
    assert explanation_cache.get(content_sha("package nothing.stored")) is None


def test_different_content_never_shares_an_entry(db_session, app_db):
    """The property the whole design rests on."""
    explanation_cache.put(content_sha(POLICY), "clusters.rego", "Original.")

    assert explanation_cache.get(content_sha(POLICY.replace("false", "true"))) is None


def test_the_same_policy_name_with_new_content_misses(db_session, app_db):
    """Keying on the file name would have returned the old reading here."""
    explanation_cache.put(content_sha(POLICY), "clusters.rego", "Original.")
    edited = f"{POLICY}\nviolations.x contains \"y\"\n"

    assert explanation_cache.get(content_sha(edited)) is None


def test_writing_the_same_key_twice_keeps_the_first(db_session, app_db):
    """Two people opening the same draft at once race on the primary key."""
    sha = content_sha(POLICY)
    explanation_cache.put(sha, "clusters.rego", "First.")
    explanation_cache.put(sha, "clusters.rego", "Second.")

    assert explanation_cache.get(sha) == "First."
    assert db_session.query(PolicyExplanationModel).count() == 1


def test_an_empty_explanation_is_not_stored(db_session, app_db):
    """Caching a failed generation would make it permanent."""
    sha = content_sha(POLICY)
    explanation_cache.put(sha, "clusters.rego", "   ")

    assert explanation_cache.get(sha) is None


# --- Degrading ---------------------------------------------------------------


def test_a_broken_database_reads_as_a_miss(monkeypatch):
    def unavailable():
        raise RuntimeError("no database")

    monkeypatch.setattr(explanation_cache, "_session", unavailable)

    assert explanation_cache.get("abc") is None


def test_a_broken_database_does_not_raise_on_write(monkeypatch):
    def unavailable():
        raise RuntimeError("no database")

    monkeypatch.setattr(explanation_cache, "_session", unavailable)

    explanation_cache.put("abc", "clusters.rego", "Something.")
