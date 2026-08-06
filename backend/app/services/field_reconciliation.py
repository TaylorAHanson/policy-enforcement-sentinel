"""Whether the field catalogue is telling the truth about the estate.

Everything else in this repository is checked *against* ``discovered_fields``.
Policies are validated against it, fixtures are refused if they invent a field
outside it, the agent is prompted from it, and ``rule_diagnosis`` decides
whether a rule is workable by consulting it. It is the root of the whole
honesty chain.

Nothing has ever checked it against reality. It is a hand-written docstring on
a Python class, and it can be wrong in three ways that all look like success:

``never_emitted``
    The handler declares a field and never sets it. Every rule reading that
    field silently never fires, and — worse than before this module existed —
    the diagnosis reports those rules as *working*, because the catalogue says
    the field is collected. This is the original bug wearing a disguise, and it
    is now invisible to every check except this one.

``undeclared``
    The handler emits a field it does not declare. Harmless to the scan and
    quietly expensive: the validator flags policies that use it, the agent does
    not know it exists, and nobody writes the rule that field would support.

And one that needs the policies as well as the estate:

``impossible_comparison``
    A rule compares a field against a literal that does not occur anywhere in
    the estate.     `access_mode == "shared"` against a fleet that only ever reports
    `USER_ISOLATION` is not a rule that found nothing — it is a rule that cannot
    find anything. Two shipped rules had exactly this shape and were found by
    hand; this finds the next one.

Those four are reported as **drift**: the catalogue and the estate disagree, and
one of them is wrong.

Separately and more quietly, a field can be declared, emitted, and empty on
every resource in the estate — `tags: {}` everywhere, or an
`autoscale_max_workers` that is null because nothing autoscales. Those are
reported as **inert** rather than as drift, and the distinction is the whole
reason this is not one list. A nullable field on an unused feature is the
handler working correctly; a field that is empty because the API stopped
returning it is a bug. They are indistinguishable from the data, so this says
what it can honestly say — no rule reading this field can fire against your
estate as it stands — and leaves the judgement to somebody who knows which
features are in use.

Observation is deliberately separated from judgement. :func:`observe` reduces a
scan to a small aggregate with no per-resource detail, which is what gets
persisted; :func:`reconcile` compares that aggregate to the catalogue. The
split means the expensive half runs once per scan and the cheap half can be
re-run against a new set of policies without rescanning.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Set

from app.providers.databricks.handlers import HANDLER_REGISTRY
from app.services import resource_schema

logger = logging.getLogger(__name__)

#: Stop recording distinct values for a field once it has this many. Above it
#: the field is free text rather than an enumeration, and the set is no longer
#: useful for catching a comparison against an impossible literal.
_MAX_DISTINCT_VALUES = 16

#: Values longer than this are prose, not enum members.
_MAX_VALUE_LENGTH = 48

#: Fields whose values are never recorded, whatever their cardinality.
#:
#: The value sets exist to catch `== "shared"` against a fleet that only reports
#: `USER_ISOLATION`. Nothing about that needs to know who owns a cluster or what
#: a notebook is called. In a small workspace those fields would fall under the
#: cardinality cap and be captured, so the cap alone is not sufficient
#: protection — this list is. Identifiers and human names stay out of an
#: aggregate that gets persisted and shipped to a UI.
_NEVER_RECORD_VALUES = {
    "id",
    "name",
    "owner",
    "path",
    "url",
    "description",
    "application_id",
    "catalog",
    "schema",
    "last_altered",
    "message",
    "shared_with",
    "principals",
    "entitlements",
    "roles",
}


def _is_populated(value: Any) -> bool:
    """Whether a value carries information.

    ``0`` and ``False`` count as populated: an autotermination of zero is a real
    setting that a rule exists to catch, and treating it as absent would hide
    the exact case that matters.
    """
    if value is None:
        return False
    if isinstance(value, (str, list, dict, tuple, set)):
        return len(value) > 0
    return True


def _recordable(field: str, value: Any) -> bool:
    if field in _NEVER_RECORD_VALUES:
        return False
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return 0 < len(value) <= _MAX_VALUE_LENGTH
    return False


def observe(resources: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Reduce discovered resources to a per-type, per-field aggregate.

    No resource ever appears in the output — only counts, and value sets for
    fields that behave like enumerations. The result is small enough to persist
    on every scan and carries nothing identifying.
    """
    types: Dict[str, Any] = {}

    for resource in resources:
        resource_type = str(resource.get("type") or "unknown")
        entry = types.setdefault(
            resource_type, {"resource_count": 0, "fields": {}}
        )
        entry["resource_count"] += 1

        for field, value in resource.items():
            stats = entry["fields"].setdefault(
                field,
                {"present": 0, "populated": 0, "values": set(), "too_many_values": False},
            )
            stats["present"] += 1
            if _is_populated(value):
                stats["populated"] += 1

            if stats["too_many_values"] or not _recordable(field, value):
                continue
            values: Set[Any] = stats["values"]
            values.add(value)
            if len(values) > _MAX_DISTINCT_VALUES:
                stats["too_many_values"] = True
                values.clear()

    # Sets are not JSON, and a stable order makes the persisted blob diffable.
    for entry in types.values():
        for stats in entry["fields"].values():
            stats["values"] = sorted(stats["values"], key=lambda v: (str(type(v)), str(v)))

    return {"resource_types": types}


# --- Comparing a rule against reality ---------------------------------------

#: `input.resource.thing == "literal"` and the reverse order.
_COMPARE = re.compile(
    r"""input\.resource\.([a-zA-Z_][a-zA-Z0-9_]*)\s*==\s*["']([^"']+)["']"""
)
_COMPARE_REVERSED = re.compile(
    r"""["']([^"']+)["']\s*==\s*input\.resource\.([a-zA-Z_][a-zA-Z0-9_]*)"""
)

#: `object.get(input.resource, "thing", default) == "literal"`.
_GET_COMPARE = re.compile(
    r"""object\.get\(\s*input\.resource\s*,\s*["']([^"']+)["']\s*,[^)]*\)\s*==\s*["']([^"']+)["']"""
)

#: `object.get(input.resource, "thing", "") in {"a", "b"}`.
_GET_IN_SET = re.compile(
    r"""object\.get\(\s*input\.resource\s*,\s*["']([^"']+)["']\s*,[^)]*\)\s+in\s+\{([^}]*)\}"""
)
_IN_SET = re.compile(
    r"""input\.resource\.([a-zA-Z_][a-zA-Z0-9_]*)\s+in\s+\{([^}]*)\}"""
)

_STRING_MEMBER = re.compile(r"""["']([^"']+)["']""")


def compared_literals(content: str) -> Dict[str, Set[str]]:
    """``{field: {literals it is compared against}}`` for one policy.

    Only equality and set membership. A comparison the estate cannot satisfy is
    the shape worth catching; ``>``, ``startswith`` and the rest are either
    open-ended or already covered by the field checks.
    """
    found: Dict[str, Set[str]] = {}

    def record(field: str, literal: str) -> None:
        found.setdefault(field, set()).add(literal)

    for field, literal in _COMPARE.findall(content):
        record(field, literal)
    for literal, field in _COMPARE_REVERSED.findall(content):
        record(field, literal)
    for field, literal in _GET_COMPARE.findall(content):
        record(field, literal)
    for field, members in list(_GET_IN_SET.findall(content)) + list(_IN_SET.findall(content)):
        for literal in _STRING_MEMBER.findall(members):
            record(field, literal)

    return found


# --- Judgement --------------------------------------------------------------


def reconcile(
    observations: Dict[str, Any],
    *,
    policy_sources: Optional[Dict[str, Dict[str, str]]] = None,
    min_resources: int = 1,
) -> Dict[str, Any]:
    """Compare an :func:`observe` aggregate to what the handlers claim.

    ``policy_sources`` is ``{resource_type: {policy_name: rego source}}`` and is
    optional; without it the impossible-comparison check is skipped and the
    field-level findings still stand.

    ``min_resources`` guards the obvious false positive: in a workspace with one
    cluster, every field that cluster happens not to set looks like a broken
    declaration. Types below the threshold are reported as inconclusive rather
    than as drift.
    """
    observed_types = observations.get("resource_types", {}) or {}
    findings: List[Dict[str, Any]] = []
    inert: List[Dict[str, Any]] = []
    per_type: List[Dict[str, Any]] = []

    for resource_type in sorted(set(observed_types) | set(HANDLER_REGISTRY)):
        seen = observed_types.get(resource_type, {})
        count = int(seen.get("resource_count", 0) or 0)
        fields = seen.get("fields", {}) or {}

        declared = set(resource_schema.resource_fields(resource_type))
        # `type` is stamped on by the scan loop rather than by the handler.
        emitted = set(fields)

        summary: Dict[str, Any] = {
            "resource_type": resource_type,
            "resource_count": count,
            "scanned": resource_type in observed_types,
            "conclusive": count >= min_resources,
            "never_emitted": [],
            "undeclared": [],
            "impossible_comparisons": [],
            "inert": [],
        }

        if resource_type not in HANDLER_REGISTRY:
            # Something emitted a type nothing is registered to discover.
            summary["unregistered"] = True
            per_type.append(summary)
            continue

        if not count:
            # Nothing to compare against. Saying so is the honest outcome; the
            # alternative is reporting every declared field as missing because
            # the workspace happens to contain none of this type.
            per_type.append(summary)
            continue

        for field in sorted(declared - emitted):
            summary["never_emitted"].append(field)
            findings.append(
                {
                    "kind": "never_emitted",
                    "resource_type": resource_type,
                    "field": field,
                    "resource_count": count,
                    "detail": (
                        f"{resource_type}'s handler declares `{field}` and did not "
                        f"set it on any of the {count} discovered. Every rule "
                        f"reading it fails to match silently, and the catalogue "
                        f"says it is collected — so those rules are currently "
                        f"reported as working."
                    ),
                }
            )

        for field in sorted(emitted - declared):
            summary["undeclared"].append(field)
            findings.append(
                {
                    "kind": "undeclared",
                    "resource_type": resource_type,
                    "field": field,
                    "resource_count": count,
                    "detail": (
                        f"{resource_type}'s handler sets `{field}` without "
                        f"declaring it. Policies reading it are flagged as using "
                        f"an unknown field, and the assistant does not know it "
                        f"is available."
                    ),
                }
            )

        for field in sorted(emitted & declared):
            stats = fields.get(field, {})
            if stats.get("present") and not stats.get("populated"):
                summary["inert"].append(field)
                inert.append(
                    {
                        "kind": "inert",
                        "resource_type": resource_type,
                        "field": field,
                        "resource_count": count,
                        "detail": (
                            f"`{field}` is set on all {count} discovered "
                            f"{resource_type}s and empty on every one of them, so "
                            f"no rule reading it can fire against this estate. "
                            f"That may be correct — a nullable field on a feature "
                            f"nobody uses looks exactly like this."
                        ),
                    }
                )

        for entry in _impossible_comparisons(
            resource_type, fields, (policy_sources or {}).get(resource_type, {})
        ):
            summary["impossible_comparisons"].append(entry)
            findings.append(entry)

        per_type.append(summary)

    return {
        "resource_types": per_type,
        # Drift: the catalogue and the estate disagree and one is wrong.
        "findings": findings,
        # Inert: they agree, and nothing reading these fields can fire today.
        "inert": inert,
        "counts": _count_kinds(findings),
        "total": len(findings),
    }


def _impossible_comparisons(
    resource_type: str,
    fields: Dict[str, Any],
    sources: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Rules comparing a field against a literal the estate never produces."""
    results: List[Dict[str, Any]] = []

    for policy_name, content in sorted(sources.items()):
        for field, literals in sorted(compared_literals(content).items()):
            stats = fields.get(field)
            if not stats:
                continue
            # An unbounded field tells us nothing: we stopped recording, so a
            # literal being absent from the set is not evidence.
            if stats.get("too_many_values") or not stats.get("values"):
                continue

            observed = {str(value) for value in stats["values"]}
            missing = sorted(literal for literal in literals if literal not in observed)
            if not missing or len(missing) != len(literals):
                # If at least one compared literal does occur, the rule has a
                # reachable branch and this is not the bug we are hunting.
                continue

            results.append(
                {
                    "kind": "impossible_comparison",
                    "resource_type": resource_type,
                    "field": field,
                    "policy": policy_name,
                    "compared_against": sorted(literals),
                    "observed_values": sorted(observed),
                    "detail": (
                        f"{policy_name} compares `{field}` against "
                        f"{', '.join(repr(m) for m in missing)}, and no "
                        f"{resource_type} in this estate reports any of those. "
                        f"The observed values are "
                        f"{', '.join(repr(v) for v in sorted(observed))}."
                    ),
                }
            )

    return results


def _count_kinds(findings: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {
        "never_emitted": 0,
        "undeclared": 0,
        "impossible_comparison": 0,
    }
    for finding in findings:
        kind = str(finding["kind"])
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def policy_sources() -> Dict[str, Dict[str, str]]:
    """``{resource_type: {policy name: rego source}}`` for the shipped policies."""
    # Imported here rather than at module scope: policy_registry shells out to
    # `opa` on first use, and this module is imported by the scan path, which
    # should not pay for that unless somebody asks for a reconciliation.
    from app.services import policy_registry

    sources: Dict[str, Dict[str, str]] = {}
    for policy in policy_registry.load_policies():
        if not policy.resource_type:
            continue
        try:
            with open(policy.file, "r", encoding="utf-8") as handle:
                sources.setdefault(policy.resource_type, {})[policy.name] = handle.read()
        except OSError as e:
            logger.warning("Could not read %s for reconciliation: %s", policy.file, e)
    return sources


def latest_observations(db) -> Optional[Dict[str, Any]]:
    """Field observations from the most recent scan that recorded any.

    ``None`` when no scan has run, which is the honest answer and a different
    thing from a scan that found no drift. The caller says which.
    """
    from app.db.sentinel_run import SentinelRunModel

    runs = (
        db.query(SentinelRunModel)
        .order_by(SentinelRunModel.id.desc())
        .limit(25)
        .all()
    )
    for run in runs:
        observations = (run.results or {}).get("field_observations")
        if observations and observations.get("resource_types"):
            return {
                "run_id": run.run_id,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "observations": observations,
            }
    return None


def report(db) -> Dict[str, Any]:
    """The drift report for the latest scan, or an explanation of its absence."""
    latest = latest_observations(db)
    if not latest:
        return {
            "available": False,
            "reason": (
                "No scan has recorded what the handlers emit yet. Run a scan "
                "against a real workspace and this will compare the field "
                "catalogue against what actually came back."
            ),
            "resource_types": [],
            "findings": [],
            "inert": [],
            "counts": _count_kinds([]),
            "total": 0,
        }

    result = reconcile(latest["observations"], policy_sources=policy_sources())
    result["available"] = True
    result["run_id"] = latest["run_id"]
    result["observed_at"] = latest["started_at"]
    return result


__all__ = [
    "compared_literals",
    "latest_observations",
    "observe",
    "policy_sources",
    "reconcile",
    "report",
]
