"""What a policy is allowed to know about each resource type.

A Rego rule can only test data that discovery actually collected. Reference a
field the handler never sets and Rego does not complain — an undefined reference
simply fails to match, the rule never fires, and every resource of that type
comes back compliant. There is no error, no warning, and nothing in a scan
result that looks different from a healthy estate.

That is not a hypothetical. Two rules in this repository were dead on arrival
for a near-identical reason (``policy_id`` arriving as null rather than absent),
and both looked like clean passes for as long as they existed. A rule about a
field that was never collected fails the same way, permanently, and no amount of
scanning will reveal it.

So the vocabulary is published: each handler declares the fields it emits, this
module gathers them, the agent is told what exists before it writes anything,
and a policy referencing something outside the vocabulary is flagged. The check
is advisory rather than blocking — Rego is a real language and there are valid
reasons to reach for a field this cannot see, such as a rule that only applies
when a key is absent — but it is loud, because the alternative is silence.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from app.providers.databricks.handlers import HANDLER_REGISTRY

logger = logging.getLogger(__name__)

#: Fields every handler sets, whatever the resource type.
#:
#: Deliberately short. The temptation is to list everything a policy *might*
#: want here, and that is precisely the mistake this module exists to catch: a
#: field listed but never collected invites the rule that cannot work. Nothing
#: goes in here that discovery does not actually produce for every type.
COMMON_RESOURCE_FIELDS: Dict[str, str] = {
    "id": "The resource identifier.",
    "type": "The resource type string.",
    "name": "A human-readable name.",
    "owner": "Who owns the resource, usually an email.",
    "tags": "A string map. Empty for types whose API has no tags.",
}

#: The other top-level objects a policy can read, which are the same for every
#: resource type.
INPUT_DOCUMENT: Dict[str, Dict[str, str]] = {
    "workspace": {
        "name": "The workspace name.",
        "type": '"enterprise" or "domain".',
        "environment": '"prod", "dev", and so on.',
    },
    "allowlist_records": {
        "": "The exceptions in force. Read through common.rego rather than directly."
    },
    "request_time": {"": "When the scan ran, as an ISO 8601 string."},
}

#: `input.resource.thing` and `input.resource["thing"]`.
_DOT = re.compile(r"\binput\.resource\.([a-zA-Z_][a-zA-Z0-9_]*)")
_BRACKET = re.compile(r"""\binput\.resource\[\s*["']([^"']+)["']\s*\]""")

#: `object.get(input.resource, "thing", default)`.
_OBJECT_GET = re.compile(
    r"""object\.get\(\s*input\.resource\s*,\s*["']([^"']+)["']"""
)


def resource_fields(resource_type: str) -> Dict[str, str]:
    """Every field a policy for this type may read, with a description."""
    handler = HANDLER_REGISTRY.get(resource_type)
    declared = dict(getattr(handler, "discovered_fields", {}) or {})
    # The handler's own description wins: "always empty, this API has no tags"
    # is more useful than the generic line, and it is the thing that stops
    # someone writing a tagging rule for a type that cannot have tags.
    return {**COMMON_RESOURCE_FIELDS, **declared}


def catalog() -> Dict[str, Any]:
    """The whole vocabulary, for the UI and the agent prompt."""
    types: List[Dict[str, Any]] = []
    for resource_type in sorted(HANDLER_REGISTRY):
        handler = HANDLER_REGISTRY[resource_type]
        declared = dict(getattr(handler, "discovered_fields", {}) or {})
        types.append(
            {
                "resource_type": resource_type,
                "handler": handler.__name__,
                "declared": bool(declared),
                "fields": [
                    {
                        "name": name,
                        "description": description,
                        "common": name in COMMON_RESOURCE_FIELDS and name not in declared,
                    }
                    for name, description in sorted(resource_fields(resource_type).items())
                ],
            }
        )

    return {"resource_types": types, "input_document": INPUT_DOCUMENT}


def referenced_fields(content: str) -> List[str]:
    """Field names a policy reads off ``input.resource``."""
    found = set()
    for pattern in (_DOT, _BRACKET, _OBJECT_GET):
        found.update(pattern.findall(content))
    return sorted(found)


def check_fields(content: str, resource_type: Optional[str]) -> List[Dict[str, str]]:
    """Fields the policy reads that discovery does not collect.

    Returns an empty list when the resource type is unknown rather than
    guessing. Flagging every field of an unrecognised type would train people to
    ignore the warning, and a warning that is ignored is worse than none.
    """
    if not resource_type or resource_type not in HANDLER_REGISTRY:
        return []

    known = resource_fields(resource_type)
    problems = []
    for name in referenced_fields(content):
        if name in known:
            continue
        problems.append(
            {
                "field": name,
                "resource_type": resource_type,
                "message": (
                    f"`input.resource.{name}` is never set for {resource_type}. "
                    f"Rego treats a missing field as no match, so this rule would "
                    f"never fire and every {resource_type} would look compliant. "
                    f"Collect the field in {resource_type}'s handler first, or use "
                    f"one of: {', '.join(sorted(known))}."
                ),
            }
        )
    return problems


def prompt_summary(resource_type: Optional[str] = None) -> str:
    """The vocabulary, formatted for a system prompt.

    Scoped to one type when the editor has a policy open, because the full
    catalogue is a few thousand tokens of mostly irrelevant fields and the
    relevant ones get lost in it.
    """
    lines: List[str] = []

    types = [resource_type] if resource_type in HANDLER_REGISTRY else sorted(HANDLER_REGISTRY)
    for name in types:
        lines.append(f"{name}:")
        for field, description in sorted(resource_fields(name).items()):
            lines.append(f"  input.resource.{field} — {description}")
        lines.append("")

    lines.append("input.workspace.name, .type, .environment are always available.")
    lines.append(
        "Anything not listed above is NOT collected. A rule referencing it will "
        "never fire, silently. Say so instead of writing the rule."
    )
    return "\n".join(lines)
