"""Hydrates the local policy directory from GitHub.

Git is the store. The directory on disk is a working copy — disposable, and
rebuilt from the target branch rather than written to.

This exists because the two constraints pull in opposite directions. OPA
evaluates a directory of files and ``opa inspect`` parses that same directory to
build the metadata registry, so policies have to exist on a local filesystem.
But an app platform gives you an ephemeral one: anything written at runtime is
gone at the next restart. Treating that directory as storage means an edit
survives exactly until the container recycles, which is the worst possible
failure mode because it looks like it worked.

So nothing writes policies here except this module, and this module only ever
copies down what is already committed. Edits go out as pull requests; merged
changes come back on the next sync.

Skipped entirely when the directory is inside a real git checkout. That is local
development, where the checkout is the working copy and clobbering it would
destroy uncommitted work.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx

from app.core.config import settings
from app.services import policy_history, policy_registry
from app.services.github_errors import github_failure_detail

logger = logging.getLogger(__name__)

#: Only these are pulled down. The directory is also where OPA looks, so a stray
#: file type would either be ignored or, worse, fail to parse the whole bundle.
_SYNCED_SUFFIXES = (".rego", ".md")

_TIMEOUT_SECONDS = 30


@dataclass
class SyncResult:
    """What the last sync did, for the status endpoint and the logs."""

    status: str
    detail: str = ""
    at: Optional[str] = None
    commit: Optional[str] = None
    written: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


#: The most recent result, served by ``GET /policies/sync`` so the UI can say
#: how old the working copy is.
_last: SyncResult = SyncResult(status="never", detail="No sync has run yet.")

_lock = asyncio.Lock()


def last_result() -> SyncResult:
    return _last


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_configured() -> bool:
    return bool(settings.GITHUB_TOKEN and settings.GITHUB_REPO)


def is_local_checkout(policies_dir: Optional[str] = None) -> bool:
    """Whether the policies directory is inside a git working tree.

    When it is, git is already the store and the developer manages it with git.
    Overwriting files from the target branch would silently discard whatever
    they have in progress.
    """
    return policy_history.is_available(policies_dir or settings.get_policies_dir)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://api.github.com",
        timeout=_TIMEOUT_SECONDS,
        headers={
            "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )


async def _fetch_manifest(client: httpx.AsyncClient) -> List[dict]:
    """The policy files on the target branch, with their blob SHAs."""
    url = (
        f"/repos/{settings.GITHUB_REPO}/contents/{settings.GITHUB_POLICIES_DIR}"
        f"?ref={settings.GITHUB_TARGET_BRANCH}"
    )
    response = await client.get(url)
    if response.status_code == 404:
        raise FileNotFoundError(
            f"{settings.GITHUB_POLICIES_DIR} does not exist on "
            f"{settings.GITHUB_TARGET_BRANCH} in {settings.GITHUB_REPO}."
        )
    if response.status_code != 200:
        raise RuntimeError(
            github_failure_detail(
                response.status_code, response.text, "Could not read the policies"
            )
        )

    return [
        item
        for item in response.json()
        if item.get("type") == "file" and item["name"].endswith(_SYNCED_SUFFIXES)
    ]


async def _fetch_file(client: httpx.AsyncClient, item: dict) -> str:
    """One file's contents.

    The directory listing omits content for anything sizeable, so the blob is
    fetched by SHA rather than trusting whatever the listing happened to inline.
    """
    response = await client.get(
        f"/repos/{settings.GITHUB_REPO}/git/blobs/{item['sha']}"
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Could not read {item['name']}: GitHub returned {response.status_code}"
        )

    payload = response.json()
    if payload.get("encoding") != "base64":
        raise RuntimeError(f"Unexpected encoding for {item['name']}.")
    return base64.b64decode(payload["content"]).decode("utf-8")


def _write_if_changed(path: str, content: str) -> bool:
    """Write only on a real difference.

    OPA watches this directory. Rewriting identical bytes would churn its file
    watcher on every sync and reload the bundle for nothing.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            if handle.read() == content:
                return False
    except OSError:
        pass

    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    return True


async def sync_policies(*, force: bool = False) -> SyncResult:
    """Rebuild the working copy from the target branch.

    Never raises. A failed sync leaves the previous working copy in place, which
    is the right call: stale policies still enforce something sensible, whereas
    an empty directory would evaluate every resource as compliant.
    """
    global _last

    if not is_configured():
        _last = SyncResult(
            status="disabled",
            detail="GitHub is not configured, so the working copy is whatever shipped with the app.",
            at=_now(),
        )
        return _last

    if is_local_checkout() and not force:
        _last = SyncResult(
            status="local",
            detail="The policies directory is a git checkout; manage it with git.",
            at=_now(),
        )
        return _last

    # Two syncs writing the same directory would race OPA's file watcher into
    # reading a half-written bundle.
    async with _lock:
        policies_dir = settings.get_policies_dir
        try:
            os.makedirs(policies_dir, exist_ok=True)

            async with _client() as client:
                manifest = await _fetch_manifest(client)
                contents: Dict[str, str] = {}
                for item in manifest:
                    contents[item["name"]] = await _fetch_file(client, item)
        except Exception as e:
            logger.warning("Could not sync policies from GitHub: %s", e)
            _last = SyncResult(
                status="failed",
                detail=str(e),
                at=_now(),
                commit=_last.commit,
            )
            return _last

        written = [
            name
            for name, content in sorted(contents.items())
            if _write_if_changed(os.path.join(policies_dir, name), content)
        ]

        # A policy deleted by a merged PR has to disappear here too, or it keeps
        # enforcing after being retired.
        removed = []
        for existing in sorted(os.listdir(policies_dir)):
            if not existing.endswith(_SYNCED_SUFFIXES) or existing in contents:
                continue
            try:
                os.remove(os.path.join(policies_dir, existing))
                removed.append(existing)
            except OSError as e:
                logger.warning("Could not remove the retired policy %s: %s", existing, e)

        if written or removed:
            policy_registry.invalidate_cache()
            logger.info(
                "Synced policies from %s@%s: %d written, %d removed.",
                settings.GITHUB_REPO,
                settings.GITHUB_TARGET_BRANCH,
                len(written),
                len(removed),
            )

        _last = SyncResult(
            status="ok",
            detail=f"{len(contents)} file(s) from {settings.GITHUB_REPO}@{settings.GITHUB_TARGET_BRANCH}.",
            at=_now(),
            written=written,
            removed=removed,
        )
        return _last


async def run_periodic_sync(interval_seconds: int) -> None:
    """Re-sync on an interval so a merged PR takes effect without a redeploy."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await sync_policies()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # sync_policies swallows its own failures; this is belt and braces
            # so the loop cannot die and silently stop tracking the branch.
            logger.warning("The periodic policy sync failed: %s", e)
