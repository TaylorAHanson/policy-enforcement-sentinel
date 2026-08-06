"""Version history for policy files, read from git.

Policies are code and live in the repository, so their history already exists —
who changed a rule, when, and what the diff was. Recording a second copy of it
in the database would be duplicated state that drifts the moment somebody edits
a policy outside the UI, which they will.

This reads the repository directly instead. On a deployment where the policies
are not in a git checkout (a container shipping only the ``policies/``
directory, for example), every function degrades to "no history available"
rather than failing — history is useful context, never a precondition.

Nothing here authors a policy change. Policy edits go through the pull request
flow in ``api/v1/endpoints/policies.py`` so they get reviewed like any other
change, and no function in this module may bypass that.

:func:`restore_from_head` is the one function that touches the working tree, and
it is the opposite of authoring: it can only discard an edit that was never
reviewed, never introduce one. It cannot produce a state that git does not
already hold.
"""
from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import asdict, dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)

_GIT_TIMEOUT_SECONDS = 15

#: Field separator for git's --format. A unit separator cannot appear in a
#: commit subject or an author name, unlike anything printable.
_SEP = "\x1f"


@dataclass
class PolicyRevision:
    """One commit that touched a policy file."""

    sha: str
    short_sha: str
    author: str
    author_email: str
    date: str
    subject: str

    def to_dict(self) -> dict:
        return asdict(self)


class GitUnavailable(RuntimeError):
    """The policies directory is not inside a usable git checkout."""


def _run_git(args: List[str], cwd: str) -> str:
    try:
        process = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as e:
        raise GitUnavailable("git is not installed in this environment.") from e
    except subprocess.TimeoutExpired as e:
        raise GitUnavailable(f"git did not respond within {_GIT_TIMEOUT_SECONDS}s.") from e

    if process.returncode != 0:
        raise GitUnavailable(
            (process.stderr or process.stdout or "git command failed").strip()
        )
    return process.stdout


def _repo_root(policies_dir: str) -> str:
    output = _run_git(["rev-parse", "--show-toplevel"], cwd=policies_dir)
    root = output.strip()
    if not root:
        raise GitUnavailable("Could not determine the repository root.")
    return root


def _safe_policy_name(policy_name: str) -> str:
    """Reject anything that is not a plain ``.rego`` file name.

    This value reaches a subprocess argument and a git pathspec. Taking only the
    basename means a caller cannot walk out of the policies directory, and the
    extension check means it cannot address arbitrary repository files.
    """
    name = os.path.basename((policy_name or "").strip())
    if not name or not name.endswith(".rego") or name.startswith("-"):
        raise ValueError(f"{policy_name!r} is not a valid policy file name.")
    return name


def _relative_path(policies_dir: str, policy_name: str) -> tuple[str, str]:
    """(repo root, path of the policy relative to it)."""
    name = _safe_policy_name(policy_name)
    root = _repo_root(policies_dir)
    absolute = os.path.join(os.path.abspath(policies_dir), name)
    return root, os.path.relpath(absolute, root)


def is_available(policies_dir: str) -> bool:
    """Whether history can be read for this deployment."""
    try:
        _repo_root(policies_dir)
        return True
    except (GitUnavailable, OSError):
        return False


def list_revisions(
    policies_dir: str, policy_name: str, limit: int = 50
) -> List[PolicyRevision]:
    """Commits that touched this policy, newest first.

    ``--follow`` means a policy that was renamed still shows the history it had
    under its old name. That matters here: the per-resource restructure renamed
    every file in the directory, and without it the entire history would appear
    to start at that commit.
    """
    root, rel_path = _relative_path(policies_dir, policy_name)

    fmt = _SEP.join(["%H", "%h", "%an", "%ae", "%aI", "%s"])
    output = _run_git(
        [
            "log",
            "--follow",
            f"--max-count={max(1, min(limit, 200))}",
            f"--format={fmt}",
            "--",
            rel_path,
        ],
        cwd=root,
    )

    revisions: List[PolicyRevision] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split(_SEP)
        if len(parts) != 6:
            logger.debug("Skipping unparseable git log line: %r", line)
            continue
        sha, short_sha, author, email, date, subject = parts
        revisions.append(
            PolicyRevision(
                sha=sha,
                short_sha=short_sha,
                author=author,
                author_email=email,
                date=date,
                subject=subject,
            )
        )
    return revisions


def last_edits(policies_dir: str, policy_names: List[str]) -> dict:
    """The most recent commit touching each policy, in a single git pass.

    A dashboard listing every policy needs one row of history each, and calling
    :func:`list_revisions` per file would be a git subprocess per policy — on
    fourteen policies that is fourteen process spawns for the first paint.

    One ``git log --name-only`` over the whole directory gives the same answer,
    walking the log once and taking the first commit seen for each path. Returns
    an empty mapping rather than raising when history is unavailable, because a
    dashboard missing a "last edited" column is still a usable dashboard.
    """
    wanted = {_safe_policy_name(name) for name in policy_names if name}
    if not wanted:
        return {}

    try:
        root = _repo_root(policies_dir)
        rel_dir = os.path.relpath(os.path.abspath(policies_dir), root)
        fmt = _SEP.join(["%H", "%h", "%an", "%ae", "%aI", "%s"])
        output = _run_git(
            # A commit prefix, then the paths it touched, then a blank line.
            ["log", "--max-count=400", f"--format=%x00{fmt}", "--name-only", "--", rel_dir],
            cwd=root,
        )
    except (GitUnavailable, ValueError, OSError) as e:
        logger.debug("Bulk policy history unavailable: %s", e)
        return {}

    found: dict = {}
    current: Optional[PolicyRevision] = None

    for line in output.splitlines():
        if line.startswith("\x00"):
            parts = line[1:].split(_SEP)
            current = PolicyRevision(*parts) if len(parts) == 6 else None
            continue

        name = os.path.basename(line.strip())
        # First commit seen for a path is the newest, since the log is ordered.
        if current and name in wanted and name not in found:
            found[name] = current.to_dict()

        if len(found) == len(wanted):
            break

    return found


def get_revision_content(policies_dir: str, policy_name: str, sha: str) -> str:
    """The policy's full text as of one commit."""
    root, rel_path = _relative_path(policies_dir, policy_name)
    revision = _validated_sha(sha)
    return _run_git(["show", f"{revision}:{rel_path}"], cwd=root)


def get_revision_diff(policies_dir: str, policy_name: str, sha: str) -> str:
    """Unified diff this commit applied to the policy."""
    root, rel_path = _relative_path(policies_dir, policy_name)
    revision = _validated_sha(sha)
    return _run_git(
        ["show", "--format=", "--patch", revision, "--", rel_path],
        cwd=root,
    )


def diff_revisions(
    policies_dir: str, policy_name: str, from_sha: str, to_sha: Optional[str] = None
) -> str:
    """Diff of the policy between two commits. ``to_sha`` defaults to the working tree."""
    root, rel_path = _relative_path(policies_dir, policy_name)
    args = ["diff", _validated_sha(from_sha)]
    if to_sha:
        args.append(_validated_sha(to_sha))
    args.extend(["--", rel_path])
    return _run_git(args, cwd=root)


def _validated_sha(sha: str) -> str:
    """Accept only hex commit ids.

    A revision reaches git as an argument, and git's revision syntax is far
    richer than it looks — ``HEAD@{...}``, ``:/text``, and ``--`` prefixes all
    mean something. Restricting to hex removes the question entirely.
    """
    candidate = (sha or "").strip()
    if not candidate or len(candidate) > 40:
        raise ValueError(f"{sha!r} is not a valid commit id.")
    if not all(c in "0123456789abcdefABCDEF" for c in candidate):
        raise ValueError(f"{sha!r} is not a valid commit id.")
    return candidate


def uncommitted_changes(policies_dir: str, policy_name: str) -> bool:
    """Whether the file in the working copy differs from the last commit.

    Nothing in the app writes policies, so this can only be an edit made outside
    it — typically by hand in a local clone. It matters because the working copy
    is what a scan actually evaluates, so a difference here means the estate is
    being judged against a rule nobody reviewed.
    """
    try:
        root, rel_path = _relative_path(policies_dir, policy_name)
        output = _run_git(["status", "--porcelain", "--", rel_path], cwd=root)
        return bool(output.strip())
    except (GitUnavailable, ValueError, OSError):
        return False


def restore_from_head(policies_dir: str, policy_name: str) -> str:
    """Discard working-copy edits to one policy and return the restored text.

    Deliberately scoped to a single file: a blanket restore would silently take
    unrelated work with it. Raises :class:`GitUnavailable` when the policies
    directory is not a checkout, which is the normal case in a deployed app —
    there the working copy is rebuilt by the sync instead.
    """
    root, rel_path = _relative_path(policies_dir, policy_name)

    # HEAD rather than a bare `--` pathspec so a staged change is dropped too.
    # Restoring the file but leaving the staged version behind would clear the
    # warning while the difference was still there.
    _run_git(["checkout", "HEAD", "--", rel_path], cwd=root)

    with open(os.path.join(root, rel_path), "r", encoding="utf-8") as handle:
        return handle.read()
