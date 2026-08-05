#!/usr/bin/env python3
"""Local-dev preflight — IDE tooling only, invoked by ``./dev.sh``.

Two jobs, both strictly local:

1. **Validate** the config the backend needs and print a grouped report of
   anything missing. Warn-only; it never blocks startup.
2. **Resolve Databricks credentials** when they are absent from ``backend/.env``
   using the developer's own CLI login, and emit ``export`` lines on stdout for
   ``dev.sh`` to evaluate — so the backend runs as *you* without hand-copying a
   token.

The reason this exists rather than leaving the SDK to sort itself out: pydantic
reads ``backend/.env`` into ``settings``, **not** into ``os.environ``. Any code
that constructs a bare ``WorkspaceClient()`` therefore ignores that file and
authenticates as whatever ``~/.databrickscfg`` names as DEFAULT. When that
profile's session has expired, the failure surfaces much later, attributed to
whatever feature happened to call it first. Exporting the resolved values makes
the ambient chain and the app's own config agree.

Guarantees:
  * **Nothing deployed is affected.** It exits before touching credentials if it
    detects the Databricks Apps runtime, and ``dev.sh`` is the only caller.
    Deployed apps use the ambient service principal.
  * **Writes nothing to disk and mints no new tokens.** It reuses whatever auth
    your CLI already has, prefers long-lived credentials, and warns when it
    falls back to a short-lived OAuth bearer.

stdout is reserved for ``export`` lines so ``dev.sh`` can ``eval`` them; every
human-readable line goes to stderr.

Usage:
    python scripts/local_dev_preflight.py            # report only
    python scripts/local_dev_preflight.py --export   # + emit `export KEY=...`
"""
from __future__ import annotations

import os
import shlex
import shutil
import sys

# Make the backend package importable regardless of the caller's cwd (this file
# lives in backend/scripts/, so backend/ is its parent's parent).
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# Git Bash on Windows often defaults to a non-UTF-8 code page, where printing a
# non-ASCII character raises. Everything below is ASCII by design; this is
# defensive so a stray character can never take the report down with it.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass


def _say(msg: str = "") -> None:
    """Human-readable output — stderr, so it never pollutes the eval'd stdout."""
    print(msg, file=sys.stderr)


def _running_on_platform() -> bool:
    """True inside the Databricks Apps runtime, which injects these."""
    return bool(
        os.environ.get("DATABRICKS_APP_PORT") or os.environ.get("DATABRICKS_APP_NAME")
    )


def _status(ok: bool) -> str:
    return "[OK]" if ok else "[!!]"


def _active_profile() -> str:
    return os.environ.get("DATABRICKS_CONFIG_PROFILE", "DEFAULT")


def _reauth_hint(profile: str) -> None:
    _say(f"    Fix: databricks auth login --profile {profile}")
    _say("         or set DATABRICKS_HOST + DATABRICKS_TOKEN in backend/.env")


def _resolve_from_cli(want_host: bool, want_creds: bool) -> dict:
    """Resolve Databricks auth from the developer's CLI profile via the SDK.

    Returns only the pieces that were requested. Prefers credentials that do not
    expire (service principal, then PAT) and falls back to a short-lived OAuth
    bearer with a warning.
    """
    try:
        from databricks.sdk.core import Config
    except Exception as e:
        _say(f"  !  Databricks SDK unavailable for auto-auth: {e}")
        return {}

    profile = _active_profile()

    try:
        cfg = Config()  # env -> .databrickscfg -> OAuth (U2M)
    except Exception as e:
        _say(f"  !  Could not resolve Databricks auth from your CLI profile: {e}")
        _reauth_hint(profile)
        return {}

    out: dict = {}

    if want_host and getattr(cfg, "host", None):
        out["DATABRICKS_HOST"] = cfg.host

    if want_creds:
        client_id = getattr(cfg, "client_id", None)
        client_secret = getattr(cfg, "client_secret", None)
        token = getattr(cfg, "token", None)

        if client_id and client_secret:
            out["DATABRICKS_CLIENT_ID"] = client_id
            out["DATABRICKS_CLIENT_SECRET"] = client_secret
            _say("  [OK] Resolved service-principal credentials from your CLI profile.")
        elif token:
            out["DATABRICKS_TOKEN"] = token
            _say("  [OK] Resolved a PAT from your CLI profile.")
        else:
            # OAuth U2M has no static token attribute, so ask the session for a
            # bearer. This is also where an expired refresh token shows up —
            # which is the whole reason to do it here, at startup, rather than
            # leaving it to surface from whichever feature calls first.
            try:
                headers = cfg.authenticate() or {}
                bearer = str(headers.get("Authorization", ""))
                if bearer.lower().startswith("bearer "):
                    out["DATABRICKS_TOKEN"] = bearer[7:].strip()
                    _say("  [OK] Resolved a short-lived OAuth token from your CLI login.")
                    _say("       NOTE: U2M tokens expire (~1h). If the backend starts")
                    _say("             returning 401s mid-session, re-run ./dev.sh.")
                else:
                    _say("  !  Your CLI session returned no usable bearer token.")
                    _reauth_hint(profile)
            except Exception as e:
                _say(f"  !  Your Databricks CLI session is not usable: {e}")
                _reauth_hint(profile)

    return out


def _report(settings, host: str, has_auth: bool) -> None:
    """A grouped view of local-dev config health. Warn-only."""
    _say("")
    _say("-- Local dev preflight ------------------------------------")

    _say(f"  {_status(bool(host))} Databricks host    {host or '(missing)'}")
    _say(
        f"  {_status(has_auth)} Databricks auth    "
        f"{'resolved' if has_auth else '(missing - run `databricks auth login`)'}"
    )

    opa = (getattr(settings, "OPA_BINARY", "") or "").strip() or shutil.which("opa")
    _say(
        f"  {_status(bool(opa))} OPA binary         "
        f"{opa or '(not found - policy evaluation will fail)'}"
    )

    agent_endpoint = (
        (getattr(settings, "AI_GATEWAY_ENDPOINT", "") or "").strip()
        or (getattr(settings, "MODEL_SERVING_AGENT_LLM_ENDPOINT", "") or "").strip()
    )
    _say(
        f"  {_status(bool(agent_endpoint))} Agent LLM endpoint {agent_endpoint or '(unset - the assistant will not respond)'}"
    )

    if (getattr(settings, "DATABASE_URL", "") or "").strip():
        _say("  [OK] Database           configured (Lakebase/Postgres)")
    else:
        _say("  [OK] Database           SQLite (local default: backend/sentinel.db)")

    # Policies are stored in git and change by pull request, so without a token
    # the Policy Editor is read-only. Worth saying here rather than letting it
    # be discovered as a disabled button.
    github_repo = (getattr(settings, "GITHUB_REPO", "") or "").strip()
    github_ready = bool((getattr(settings, "GITHUB_TOKEN", "") or "").strip() and github_repo)
    _say(
        f"  {_status(github_ready)} Policy editing     "
        + (
            f"pull requests to {github_repo}@{getattr(settings, 'GITHUB_TARGET_BRANCH', 'main')}"
            if github_ready
            else "read-only (set GITHUB_TOKEN and GITHUB_REPO to open PRs)"
        )
    )

    # Enforcement last, and stated either way. This is the one line worth
    # reading every single time the backend starts.
    if getattr(settings, "ENFORCEMENT_ENABLED", False):
        workspaces = (getattr(settings, "DESTRUCTIVE_ACTION_WORKSPACES", "") or "").strip()
        _say("")
        _say("  ** ENFORCEMENT IS ENABLED **")
        _say(f"     Destructive actions are permitted in: {workspaces or '(no workspaces listed)'}")
        _say(f"     Scheduled scans run in: {getattr(settings, 'SENTINEL_CRON_MODE', 'audit')}")
    else:
        _say("  [OK] Enforcement        disabled (actions downgrade to WARN)")

    if not host or not has_auth:
        _say("")
        _say("  Databricks config is incomplete. Easiest fix:")
        _say(f"    databricks auth login --profile {_active_profile()}")
        _say("  ...then re-run ./dev.sh. No need to paste a token into .env.")

    _say("-----------------------------------------------------------")
    _say("")


def main() -> int:
    export_mode = "--export" in sys.argv[1:]

    # Hard boundary: never touch credentials on a deployed runtime.
    if _running_on_platform():
        _say("local_dev_preflight: Databricks Apps runtime detected - skipping.")
        return 0

    try:
        from app.core.config import settings
    except Exception as e:
        _say(f"local_dev_preflight: could not import app config ({e}); skipping.")
        return 0

    host = (
        (getattr(settings, "DATABRICKS_HOST", "") or "")
        or (getattr(settings, "DATABRICKS_WORKSPACE_URL", "") or "")
    ).strip()
    has_token = bool((getattr(settings, "DATABRICKS_TOKEN", "") or "").strip())
    has_sp = bool(
        (getattr(settings, "DATABRICKS_CLIENT_ID", "") or "").strip()
        and (getattr(settings, "DATABRICKS_CLIENT_SECRET", "") or "").strip()
    )

    exports: dict = {}
    if not host or not (has_token or has_sp):
        _say("  Databricks credentials incomplete in backend/.env - trying your CLI login...")
        exports = _resolve_from_cli(want_host=not host, want_creds=not (has_token or has_sp))
    else:
        # Already configured. Export them anyway so the ambient SDK chain agrees
        # with the app's own settings: pydantic loaded these from .env into
        # `settings` only, and anything constructing a bare WorkspaceClient()
        # would otherwise authenticate as a different identity entirely.
        exports["DATABRICKS_HOST"] = host
        if has_token:
            exports["DATABRICKS_TOKEN"] = settings.DATABRICKS_TOKEN
        if has_sp:
            exports["DATABRICKS_CLIENT_ID"] = settings.DATABRICKS_CLIENT_ID
            exports["DATABRICKS_CLIENT_SECRET"] = settings.DATABRICKS_CLIENT_SECRET

    resolved_host = exports.get("DATABRICKS_HOST", host)
    resolved_auth = (
        has_token
        or has_sp
        or "DATABRICKS_TOKEN" in exports
        or ("DATABRICKS_CLIENT_ID" in exports and "DATABRICKS_CLIENT_SECRET" in exports)
    )

    _report(settings, host=resolved_host, has_auth=bool(resolved_auth))

    if export_mode:
        for key, value in exports.items():
            if value:
                # Quoted so dev.sh can `eval` the line verbatim.
                sys.stdout.write(f"export {key}={shlex.quote(str(value))}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
