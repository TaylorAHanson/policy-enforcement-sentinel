"""Renaming a policy without orphaning what points at it.

A policy's name is not just a filename. Allowlist exceptions store it, saved
dashboard filters store it, historical findings record it, and links into the
editor contain it. Moving the file alone would leave every one of those pointing
at something that no longer exists — and the failure is silent, because an
exception that matches nothing simply stops suppressing, which looks like the
rule getting stricter rather than like a broken reference.

So a rename here is three edits to one file, not a move:

1. the file is written under the new name and the old one deleted,
2. the ``package`` declaration is rewritten to match, because OPA resolves rules
   by package and a mismatched declaration would leave the policy loaded under
   its old name regardless of what the file is called,
3. the former name is recorded in ``custom.replaces``, which is what keeps
   stored references resolving.

Point three lives in the policy's own metadata rather than a lookup table in
application code, so the alias travels with the file through the normal sync and
takes effect when the pull request merges rather than when the app is next
deployed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

#: A policy name is a Rego package path segment and a file stem at once, so it
#: has to be valid as both: lowercase, digits and underscores.
_VALID_NAME = re.compile(r"^[a-z][a-z0-9_]*$")

_PACKAGE_LINE = re.compile(r"^(\s*package\s+)(\S+)(.*)$", re.MULTILINE)

#: The `custom` block inside a `# METADATA` comment, whose entries are indented
#: comment lines. Captures the block's indentation so an inserted key matches.
_CUSTOM_BLOCK = re.compile(r"^(#\s*)custom:\s*$", re.MULTILINE)

_REPLACES_KEY = re.compile(
    r"^#(\s+)replaces:\s*\[(?P<items>[^\]]*)\]\s*$", re.MULTILINE
)


class RenameError(ValueError):
    """The rename cannot be performed as asked."""


@dataclass
class Rename:
    """The result of rewriting a policy for its new name."""

    old_name: str
    new_name: str
    old_package: str
    new_package: str
    content: str


def normalise(name: str) -> str:
    """A bare package name from either ``x`` or ``x.rego``."""
    stem = (name or "").strip()
    if stem.endswith(".rego"):
        stem = stem[: -len(".rego")]
    return stem


def validate_name(name: str) -> str:
    stem = normalise(name)
    if not stem:
        raise RenameError("A policy needs a name.")
    if not _VALID_NAME.match(stem):
        raise RenameError(
            f"{stem!r} will not work as both a filename and a Rego package. Use "
            "lowercase letters, digits and underscores, starting with a letter — "
            "for example `sql_warehouses`."
        )
    if len(stem) > 64:
        raise RenameError("That name is too long; keep it under 64 characters.")
    return stem


def current_package(content: str) -> Optional[str]:
    match = _PACKAGE_LINE.search(content)
    return match.group(2).strip() if match else None


def _rewrite_package(content: str, new_stem: str) -> tuple[str, str]:
    """Point the package declaration at the new name, keeping its prefix."""
    match = _PACKAGE_LINE.search(content)
    if not match:
        raise RenameError(
            "This file has no `package` declaration, so it is not a policy this "
            "can rename safely."
        )

    old_package = match.group(2).strip()
    prefix = old_package.rsplit(".", 1)[0] if "." in old_package else ""
    new_package = f"{prefix}.{new_stem}" if prefix else new_stem

    rewritten = (
        content[: match.start()]
        + f"{match.group(1)}{new_package}{match.group(3)}"
        + content[match.end():]
    )
    return rewritten, old_package


def _short(package: str) -> str:
    return package.rsplit(".", 1)[-1]


def _record_replaces(content: str, former: List[str]) -> str:
    """Add or extend ``custom.replaces`` in the METADATA block.

    Existing entries are kept and merged. A policy renamed twice has to keep
    redirecting from both of its previous names, or the first rename's
    references break the moment the second one merges.
    """
    if not former:
        return content

    existing_match = _REPLACES_KEY.search(content)
    if existing_match:
        current = [
            item.strip().strip("\"'")
            for item in existing_match.group("items").split(",")
            if item.strip()
        ]
        merged = current + [f for f in former if f not in current]
        indent = existing_match.group(1)
        line = f"#{indent}replaces: [{', '.join(merged)}]"
        return content[: existing_match.start()] + line + content[existing_match.end():]

    custom_match = _CUSTOM_BLOCK.search(content)
    if not custom_match:
        raise RenameError(
            "This policy has no `custom:` block in its METADATA, so there is "
            "nowhere to record the old name. Add one before renaming, or the "
            "rename would break every exception that names this policy."
        )

    # Match the indentation of whatever line follows `custom:`, falling back to
    # two spaces, so the inserted key lines up with its siblings.
    tail = content[custom_match.end():]
    sibling = re.search(r"^#(\s+)\S+:", tail, re.MULTILINE)
    indent = sibling.group(1) if sibling else "  "

    line = f"\n#{indent}replaces: [{', '.join(former)}]"
    return content[: custom_match.end()] + line + content[custom_match.end():]


def rename(content: str, old_name: str, new_name: str) -> Rename:
    """Rewrite a policy so it can be committed under a new name."""
    old_stem = validate_name(old_name)
    new_stem = validate_name(new_name)

    if old_stem == new_stem:
        raise RenameError("That is already the policy's name.")

    rewritten, old_package = _rewrite_package(content, new_stem)
    former = [_short(old_package)]
    rewritten = _record_replaces(rewritten, former)

    return Rename(
        old_name=f"{old_stem}.rego",
        new_name=f"{new_stem}.rego",
        old_package=old_package,
        new_package=(current_package(rewritten) or new_stem),
        content=rewritten,
    )
