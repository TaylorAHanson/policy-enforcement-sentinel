"""Release notes, read from ``docs/release-notes/`` at request time.

Markdown files on disk rather than rows in a table. They are written in the
pull request that makes the change, reviewed with it, and versioned by the same
commit — which is the only arrangement where the notes and the behaviour they
describe cannot get out of step.

Reading the directory per request costs a handful of small file reads and means
a deployment never serves notes from a stale cache.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter()

_FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
_VERSION_FILE = re.compile(r"^(\d+(?:\.\d+)*)\.md$")


@dataclass
class Release:
    version: str
    date: str
    title: str
    highlight: str
    body: str


def release_notes_dir() -> Path:
    """``docs/release-notes/``, relative to the repository root.

    This file is ``backend/app/api/v1/endpoints/release_notes.py``, so the repo
    root is five levels up from ``app``.
    """
    from app.core.config import settings

    configured = getattr(settings, "RELEASE_NOTES_DIR", "") or ""
    if configured:
        return Path(configured)

    backend = Path(__file__).resolve().parents[4]
    return backend.parent / "docs" / "release-notes"


def _version_key(version: str) -> Tuple[int, ...]:
    """Sort semantically: 1.10.0 is newer than 1.9.0, not older."""
    parts = []
    for piece in version.split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _parse_front_matter(text: str) -> Tuple[dict, str]:
    """A deliberately small YAML subset: flat ``key: value`` pairs.

    Pulling in a YAML parser to read five keys out of a file this project
    controls the format of would be a dependency for its own sake.
    """
    match = _FRONT_MATTER.match(text)
    if not match:
        return {}, text

    meta: dict = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip("\"'")
    return meta, match.group(2)


def load_releases(directory: Optional[Path] = None) -> List[Release]:
    """Every release, newest first. A missing directory yields nothing."""
    directory = directory or release_notes_dir()
    if not directory.is_dir():
        logger.info("No release notes directory at %s.", directory)
        return []

    releases: List[Release] = []
    for name in os.listdir(directory):
        match = _VERSION_FILE.match(name)
        if not match:
            # README.md and anything else that is not a version.
            continue

        path = directory / name
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("Could not read %s: %s", path, e)
            continue

        meta, body = _parse_front_matter(text)
        version = meta.get("version") or match.group(1)
        releases.append(
            Release(
                version=version,
                date=meta.get("date", ""),
                title=meta.get("title", f"Version {version}"),
                highlight=meta.get("highlight", ""),
                body=body.strip(),
            )
        )

    releases.sort(key=lambda r: _version_key(r.version), reverse=True)
    return releases


@router.get("")
@router.get("/")
async def list_releases():
    """Every release. The frontend renders the bodies as Markdown."""
    releases = load_releases()
    return {
        "releases": [asdict(r) for r in releases],
        "latest_version": releases[0].version if releases else None,
        "latest_highlight": releases[0].highlight if releases else "",
    }


@router.get("/latest")
async def latest_release():
    """Just the newest, for the Release Notes badge.

    Separate from the list so the sidebar can check for a new version on every
    page load without pulling down every release body.
    """
    releases = load_releases()
    if not releases:
        return {"version": None, "title": "", "highlight": "", "date": ""}

    newest = releases[0]
    return {
        "version": newest.version,
        "title": newest.title,
        "highlight": newest.highlight,
        "date": newest.date,
    }


@router.get("/{version}")
async def get_release(version: str):
    for release in load_releases():
        if release.version == version:
            return asdict(release)
    raise HTTPException(status_code=404, detail=f"No release notes for {version!r}.")
