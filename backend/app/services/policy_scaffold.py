"""The starting text for a new policy.

A blank editor is the wrong place to begin. A policy has a required shape — the
METADATA block the registry reads, the ``rule_metadata`` map the action ladder
reads, the ``applies`` guard, and the four summary bindings the scanner calls —
and none of that is guessable. Starting from an empty file means the first
several validation attempts are all about scaffolding rather than about the rule
somebody actually wanted.

So a new policy arrives complete and already valid, with exactly one rule that
does the least interesting possible thing: check that the resource carries an
owner tag. It is a real rule, it fires, and it is a template for the next one.

The generated rule is deliberately Tier 1 (``WARN``, ``destructive: false``).
Everything in this repository ships at Tier 1 and escalating is a deliberate
edit, so the scaffold must not be the thing that quietly introduces a higher
tier — the safety suite asserts that no shipped rule exceeds NOTIFY, and a
template producing anything stronger would make the first PR the exception.
"""
from __future__ import annotations

import re
from typing import Optional

from app.services.policy_rename import RenameError, validate_name

#: Rule ID prefixes by category, matching the shipped convention: CST for cost,
#: CTL for control, SEC for security.
_CATEGORY_PREFIX = {
    "cost": "CST",
    "control": "CTL",
    "security": "SEC",
}


def _abbreviation(resource_type: str) -> str:
    """A three-letter tag for a resource type, as used in rule IDs.

    `cluster` becomes CLU, `sql_warehouse` becomes WHS in the shipped files, so
    this cannot be derived reliably — it takes the first three letters of the
    last word and leaves correcting it to the author.
    """
    word = (resource_type or "resource").split("_")[-1]
    return (word[:3] or "res").upper()


def _title(resource_type: str) -> str:
    return f"{(resource_type or 'resource').replace('_', ' ').title()} governance"


def starter_policy(
    name: str,
    *,
    resource_type: str,
    owner: str = "",
    domain: str = "",
    title: str = "",
    description: str = "",
) -> str:
    """A complete, valid, Tier 1 policy with one working rule."""
    stem = validate_name(name)

    resource = (resource_type or "").strip()
    if not resource:
        raise RenameError("A policy has to say which resource type it governs.")
    if not re.match(r"^[a-z][a-z0-9_]*$", resource):
        raise RenameError(
            f"{resource!r} is not a resource type. Use the lowercase name the "
            "handler reports, such as `cluster` or `sql_warehouse`."
        )

    rule_id = f"{_CATEGORY_PREFIX['control']}-{_abbreviation(resource)}-001"
    heading = title.strip() or _title(resource)
    blurb = (description or "").strip() or (
        f"Rules for {resource.replace('_', ' ')} resources.\n"
        "\n"
        "Replace this description with what these rules are for and, more\n"
        "usefully, what they deliberately do not cover."
    )
    # The description is a YAML block scalar in a comment, so every line after
    # the first needs the comment marker and the block's indentation.
    blurb_lines = "\n".join(f"#   {line}".rstrip() for line in blurb.splitlines())

    return f"""\
# METADATA
# title: {heading}
# description: |
{blurb_lines}
#
#   This policy was scaffolded from the policy dashboard. Every rule below is
#   Tier 1: it warns and records, and changes nothing in the workspace.
# authors:
# - {owner or "unknown@company.com"}
# custom:
#   owner: {owner or "unknown"}
#   domain: {domain or resource}
#   resource_type: {resource}
package databricks.governance.{stem}

import data.databricks.governance.common
import future.keywords.contains
import future.keywords.if
import future.keywords.in

rule_metadata := {{
	"missing_owner_tag": {{
		"id": "{rule_id}",
		"category": "control",
		"description": "Every {resource.replace('_', ' ')} should carry an 'owner' tag, so there is somebody to ask about it.",
		"severity": "LOW",
		"requested_action": "WARN",
		"destructive": false,
	}},
}}

default applies := false

applies if {{
	input.resource.type == "{resource}"
}}

# Only reads fields the handler for this resource type actually collects. A rule
# reading anything else is valid Rego that can never match, so it reports every
# resource as compliant forever. The Tests tab checks this.
violations.missing_owner_tag contains msg if {{
	applies
	not input.resource.tags.owner
	msg := "Missing the 'owner' tag, so there is nobody to notify about this {resource.replace('_', ' ')}."
}}

default rule_results := []

rule_results := common.results(rule_metadata, violations) if {{
	applies
}}

summary := common.summarize(rule_metadata, violations) if {{
	applies
}} else := common.not_applicable

action := summary.action

is_violation := summary.is_violation

reason := summary.reason

severity := summary.severity
"""


def suggest_name(resource_type: str, existing: Optional[list] = None) -> str:
    """A plural, unused file stem for a resource type."""
    base = (resource_type or "policy").strip().lower() or "policy"
    candidate = base if base.endswith("s") else f"{base}s"

    taken = {
        (n[: -len(".rego")] if n.endswith(".rego") else n) for n in (existing or [])
    }
    if candidate not in taken:
        return candidate

    for suffix in range(2, 100):
        attempt = f"{candidate}_{suffix}"
        if attempt not in taken:
            return attempt
    return candidate
