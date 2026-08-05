"""Whether a GitHub failure tells the operator what to do next.

Every one of these started life as a raw API body pasted into the UI. The test
that matters is not that a message exists, but that it names the remedy.
"""
from __future__ import annotations

import json

import pytest

from app.core.config import settings
from app.services.github_errors import github_failure_detail


SAML_BODY = json.dumps(
    {
        "message": (
            "Resource protected by organization SAML enforcement. You must grant "
            "your Personal Access token access to an organization within this "
            "enterprise."
        ),
        "documentation_url": "https://docs.github.com/articles/authenticating-to-a-github-organization-with-saml-single-sign-on/",
        "status": "403",
    }
)


@pytest.fixture(autouse=True)
def repo(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_REPO", "databricks-field-eng/sentinel")


def test_the_saml_failure_names_the_fix_and_the_org():
    """The remedy is a checkbox on github.com, which the raw body never says."""
    detail = github_failure_detail(403, SAML_BODY, "Could not open the pull request")

    assert "Configure SSO" in detail
    assert "databricks-field-eng" in detail
    assert "https://github.com/settings/tokens" in detail


def test_the_saml_failure_says_the_token_is_not_the_problem():
    """Otherwise the obvious response is to reissue a token that was always fine."""
    detail = github_failure_detail(403, SAML_BODY, "Could not read the branch")

    assert "token itself is valid" in detail


def test_a_rejected_token_is_distinguished_from_an_unauthorised_one():
    detail = github_failure_detail(
        401, json.dumps({"message": "Bad credentials"}), "Could not commit"
    )

    assert "expired, revoked, or mistyped" in detail
    assert "SSO" not in detail


def test_a_404_explains_that_it_may_be_a_permission_problem():
    """GitHub hides private repositories behind 404, so the name looks wrong
    when the real fault is the token's access."""
    detail = github_failure_detail(
        404, json.dumps({"message": "Not Found"}), "Could not read the policies"
    )

    assert "databricks-field-eng/sentinel" in detail
    assert "missing rather than forbidden" in detail


def test_a_rate_limit_says_it_will_pass_on_its_own():
    detail = github_failure_detail(
        403,
        json.dumps({"message": "API rate limit exceeded for user"}),
        "Could not commit",
    )

    assert "rate limit" in detail.lower()
    assert "resets" in detail


def test_an_unrecognised_failure_keeps_github_s_own_message():
    """Better GitHub's specific words than a vague catch-all of ours."""
    detail = github_failure_detail(
        422, json.dumps({"message": "Reference already exists"}), "Could not branch"
    )

    assert detail == "Could not branch: Reference already exists"


def test_a_body_that_is_not_json_survives():
    detail = github_failure_detail(500, "<html>502 Bad Gateway</html>", "Could not commit")

    assert "502 Bad Gateway" in detail


def test_the_action_always_leads_so_the_reader_knows_what_failed():
    for status, body in ((403, SAML_BODY), (401, "{}"), (404, "{}"), (500, "boom")):
        assert github_failure_detail(status, body, "Could not open the PR").startswith(
            "Could not open the PR"
        )
