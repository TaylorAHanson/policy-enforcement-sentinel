"""Readable explanations for GitHub API failures.

The raw API body is accurate and useless. An operator told

    {"message": "Resource protected by organization SAML enforcement. You must
    grant your Personal Access token access to an organization within this
    enterprise.", "status": "403"}

still has to work out that the fix is one checkbox on github.com, and that
nothing is wrong with the token itself.

Only the auth failures are translated, because those are the ones every new
deployment hits and the ones whose remedy is least obvious. Anything else keeps
GitHub's own message, which is usually specific enough.
"""
from __future__ import annotations

import json

from app.core.config import settings


def github_failure_detail(status_code: int, body: str, action: str) -> str:
    """``action`` is what was being attempted, e.g. "Could not open the PR"."""
    try:
        message = json.loads(body).get("message", body)
    except (ValueError, AttributeError, TypeError):
        message = body

    org = (settings.GITHUB_REPO or "").split("/")[0] or "the organisation"
    lowered = str(message).lower()

    if "saml" in lowered or "single sign-on" in lowered:
        return (
            f"{action}: the GitHub token has not been authorised for {org}, which "
            "enforces SAML single sign-on. Open https://github.com/settings/tokens, "
            f"find this token, choose 'Configure SSO', and authorise it for {org}. "
            "The token itself is valid; it just cannot see the organisation yet."
        )

    if status_code == 401 or "bad credentials" in lowered:
        return (
            f"{action}: GitHub rejected the token. It is expired, revoked, or "
            "mistyped. Issue a new one and update GITHUB_TOKEN."
        )

    if "rate limit" in lowered:
        return f"{action}: GitHub's rate limit was reached. It resets within the hour."

    if status_code == 404:
        # GitHub returns 404 rather than 403 for a private repository the token
        # cannot see, so "not found" here usually means "not permitted".
        return (
            f"{action}: GitHub cannot find {settings.GITHUB_REPO}. Either the "
            "repository name is wrong, or the token lacks access to it — a private "
            "repository the token cannot read is reported as missing rather than "
            "forbidden."
        )

    if status_code == 403:
        return (
            f"{action}: GitHub refused the request ({message}). The token most "
            "likely lacks write access to contents or pull requests on "
            f"{settings.GITHUB_REPO}."
        )

    return f"{action}: {message}"
