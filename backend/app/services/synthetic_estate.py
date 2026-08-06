"""Policies run against a made-up estate, with no Databricks anywhere near it.

The question this answers is "does this rule fire on the thing I think it fires
on?", and until now the only way to find out was to scan a real workspace and
read the findings — slow, dependent on somebody's estate happening to contain a
matching resource, and impossible before a policy is merged.

What is faked is exactly one thing: discovery. Everything downstream is the code
that runs in production — the real ``opa`` binary, the real policies directory,
the real per-rule result shape, and the real enforcement chokepoint deciding
what the requested action resolves to. A fixture that passes here has been
through the same path a scanned resource would.

No workspace client is ever constructed here. That is what makes "this makes no
Databricks calls" a property of the code rather than an intention: the client is
built in ``SentinelService.__init__``, this module never instantiates one, and
the only thing it borrows from that class is a static pure function that turns
OPA output into findings.

A fixture states what it expects. Rules named in ``expect.fires`` must produce a
violation, rules in ``expect.passes`` must be evaluated and pass, and — the part
that catches the errors people actually make — a rule that fires without being
listed is a failure too. A policy quietly widening to catch resources it was
never meant to is the same class of mistake as an empty selector matching
everything, and it is just as invisible in a dashboard.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.enforcement import ActionRequest, ScanMode, resolve_effective_action

logger = logging.getLogger(__name__)

#: Where hand-written and captured fixtures live. Under ``backend/`` so it syncs
#: to the deployed app along with everything else in there.
FIXTURES_DIRNAME = os.path.join("fixtures", "synthetic")


#: The package prefix every policy lives under.
GOVERNANCE_NAMESPACE = "databricks.governance"


class FixtureError(ValueError):
    """A fixture file that cannot be read or does not describe a resource."""


@dataclass
class Draft:
    """Unsaved editor content to test in place of the committed file.

    Only one policy can be drafted at a time, which matches the editor: there is
    one file open. The rest of the namespace is loaded from disk as usual, so a
    draft is still evaluated alongside its neighbours and the shared library.
    """

    policy_name: str
    content: str


@dataclass
class Fixture:
    """One made-up resource, and what the policies should say about it."""

    name: str
    resource: Dict[str, Any]
    workspace: str = "synthetic-workspace"
    environment: str = "dev"
    #: "enterprise" or "domain". Several rules are scoped to enterprise
    #: production, and this used to be inferred from whether the workspace name
    #: happened to contain the word "enterprise" — which nothing told the person
    #: writing the fixture, so a rule they expected to fire silently did not.
    workspace_type: Optional[str] = None
    allowlist_records: List[Dict[str, Any]] = field(default_factory=list)
    #: Rule IDs that must produce a violation.
    fires: List[str] = field(default_factory=list)
    #: Rule IDs that must be evaluated and pass.
    passes: List[str] = field(default_factory=list)
    description: str = ""
    source: str = "handwritten"

    @property
    def resource_type(self) -> str:
        return str(self.resource.get("type") or "")

    @property
    def invented_fields(self) -> List[str]:
        """Fields this fixture supplies that no handler ever collects.

        A fixture builds the input document directly, bypassing discovery, so it
        can hand the policies anything — including data the real scanner has no
        way to produce. A rule exercised only that way passes its test and stays
        dead in the estate, which is worse than having no test, because the
        green tick is read as evidence.

        Every cluster fixture in this repository did this with ``idle_days``,
        and one of them asserted that an idleness rule *fires* — a rule that
        cannot fire against a real workspace.
        """
        from app.services import resource_schema

        if self.resource_type not in resource_schema.HANDLER_REGISTRY:
            return []
        known = set(resource_schema.resource_fields(self.resource_type))
        return sorted(set(self.resource) - known)


def _as_ids(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value if str(item).strip()]


def parse_fixture(name: str, payload: Dict[str, Any]) -> Fixture:
    resource = payload.get("resource")
    if not isinstance(resource, dict) or not resource.get("type"):
        raise FixtureError(
            f"{name}: needs a `resource` object with a `type`. Without a type no "
            "policy will claim it and the fixture would pass by never being "
            "evaluated."
        )

    expect = payload.get("expect") or {}
    if not isinstance(expect, dict):
        raise FixtureError(f"{name}: `expect` must be an object.")

    return Fixture(
        name=name,
        resource=resource,
        workspace=str(payload.get("workspace") or "synthetic-workspace"),
        environment=str(payload.get("environment") or "dev"),
        workspace_type=(
            str(payload["workspace_type"]) if payload.get("workspace_type") else None
        ),
        allowlist_records=list(payload.get("allowlist_records") or []),
        fires=_as_ids(expect.get("fires")),
        passes=_as_ids(expect.get("passes")),
        description=str(payload.get("description") or ""),
        source=str(payload.get("source") or "handwritten"),
    )


def fixtures_dir() -> str:
    from app.core.config import settings

    configured = getattr(settings, "SYNTHETIC_FIXTURES_DIR", None)
    if configured:
        return str(configured)

    # Sibling of the policies directory's parent, i.e. backend/fixtures/synthetic.
    backend_root = os.path.dirname(os.path.abspath(settings.get_policies_dir))
    return os.path.join(backend_root, FIXTURES_DIRNAME)


def load_fixtures(directory: Optional[str] = None) -> List[Fixture]:
    """Every fixture on disk, sorted by name. A broken file is skipped, loudly."""
    directory = directory or fixtures_dir()
    if not os.path.isdir(directory):
        return []

    loaded: List[Fixture] = []
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(directory, filename)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            loaded.append(parse_fixture(filename[: -len(".json")], payload))
        except (OSError, ValueError) as e:
            logger.warning("Skipping fixture %s: %s", filename, e)
    return loaded


# --- Running ----------------------------------------------------------------


def _input_for(fixture: Fixture) -> Dict[str, Any]:
    """The same document a scan builds, assembled from the fixture."""
    return {
        "workspace": {
            "name": fixture.workspace,
            # Explicit when the fixture says so. The name sniff is kept only so
            # fixtures written before `workspace_type` existed still mean what
            # they did, and it is the reason several rules scoped to enterprise
            # production looked unreachable when they were merely untested.
            "type": fixture.workspace_type
            or ("enterprise" if "enterprise" in fixture.workspace else "domain"),
            "environment": fixture.environment,
        },
        "resource": fixture.resource,
        "request_time": datetime.now(timezone.utc).isoformat(),
        "allowlist_records": fixture.allowlist_records,
    }


#: Packages in the namespace that are libraries rather than policies. Mirrors
#: the filtering ``evaluate_namespace`` does, which the draft path bypasses.
_NON_POLICY = {"common", "metadata"}


async def _evaluate(fixture: Fixture, opa, draft: Optional[Draft]) -> Dict[str, Any]:
    """Run the namespace, optionally with one policy replaced by a draft.

    Testing the committed file is the wrong default when someone is halfway
    through editing: the whole point of running a test from the editor is to
    find out whether the change in front of them works, and the change is not
    on disk yet.
    """
    if draft is None:
        return await opa.evaluate_namespace(_input_for(fixture))

    raw = await opa.evaluate_content(
        policy_name=draft.policy_name,
        content=draft.content,
        query=f"data.{GOVERNANCE_NAMESPACE}",
        input_data=_input_for(fixture),
    )

    if not isinstance(raw, dict):
        return {}

    return {
        package: result
        for package, result in raw.items()
        if package not in _NON_POLICY and isinstance(result, dict)
    }


async def run_fixture(
    fixture: Fixture, opa, draft: Optional[Draft] = None
) -> Dict[str, Any]:
    """Evaluate one fixture and compare the result against what it expects."""
    # The class, for one static method. Never instantiated: that is what would
    # build a workspace client.
    from app.services.sentinel_service import SentinelService

    try:
        results = await _evaluate(fixture, opa, draft)
    except Exception as e:
        logger.error("Synthetic evaluation failed for %s: %s", fixture.name, e)
        return {
            "fixture": fixture.name,
            "description": fixture.description,
            "resource_type": fixture.resource_type,
            "source": fixture.source,
            "passed": False,
            "error": f"{type(e).__name__}: {e}",
            "rules": [],
            # Every problem key is present even here, so a caller can read the
            # result without checking which shape it got.
            "unexpected": [],
            "missing": [],
            "not_evaluated": [],
            "wrongly_fired": [],
        }

    findings: List[Dict[str, Any]] = []
    for policy_name, result in results.items():
        findings.extend(
            SentinelService._findings_from_result(policy_name, result, fixture.resource)
        )

    rules: List[Dict[str, Any]] = []
    fired: List[str] = []
    evaluated: List[str] = []

    for finding in findings:
        rule_id = str(finding.get("policy_id") or finding.get("rule_id") or "")
        if not rule_id:
            continue
        evaluated.append(rule_id)

        violated = finding.get("kind") == "violation"
        if violated:
            fired.append(rule_id)

        # Only a violation has an action to resolve. A passing rule carries no
        # requested action at all, and putting that None through the chokepoint
        # would make it report an unrecognised action and fall back — turning
        # every compliant rule into a spurious downgrade in the results table.
        effective = None
        if violated:
            # The chokepoint, unchanged and unbypassed. What a fixture reports
            # as the effective action is what a real scan would do with the
            # settings this deployment currently has — including enforcement
            # being off, which is the answer people are most often surprised by.
            effective = resolve_effective_action(
                ActionRequest(
                    requested_action=finding.get("requested_action"),
                    resource_type=fixture.resource_type,
                    resource_id=str(fixture.resource.get("id", "")),
                    workspace=fixture.workspace,
                    mode=ScanMode.AUDIT,
                    policy_declares_destructive=bool(finding.get("destructive")),
                    # No handler exists here, so the capability gate is skipped
                    # rather than faked. Claiming a verb is supported would be
                    # the one place a synthetic run could report an action a
                    # real scan would refuse.
                    supported_methods=None,
                    destructive_candidate_count=0,
                )
            )

        rules.append(
            {
                "rule_id": rule_id,
                "policy": finding.get("policy"),
                "fired": violated,
                "severity": finding.get("severity"),
                "message": finding.get("message"),
                "requested_action": finding.get("requested_action"),
                "effective_action": effective.action if effective else None,
                "downgraded": bool(effective and effective.downgraded),
                "downgrade_reason": effective.downgrade_reason if effective else None,
            }
        )

    fired_set = set(fired)
    evaluated_set = set(evaluated)

    missing = sorted(set(fixture.fires) - fired_set)
    # A rule firing that the fixture did not ask about. Caught deliberately: a
    # policy widening to catch resources it was never meant to is invisible
    # otherwise, and looks like the system working.
    unexpected = sorted(fired_set - set(fixture.fires))
    not_evaluated = sorted(set(fixture.passes) - evaluated_set)
    wrongly_fired = sorted(set(fixture.passes) & fired_set)

    problems = {
        "missing": missing,
        "unexpected": unexpected,
        "not_evaluated": not_evaluated,
        "wrongly_fired": wrongly_fired,
    }

    return {
        "fixture": fixture.name,
        "description": fixture.description,
        "resource_type": fixture.resource_type,
        "source": fixture.source,
        "passed": not any(problems.values()),
        "error": None,
        "rules": sorted(rules, key=lambda r: r["rule_id"]),
        **problems,
    }


# --- Coverage ---------------------------------------------------------------


def rule_coverage(
    *,
    resource_type: Optional[str] = None,
    policy_name: Optional[str] = None,
    directory: Optional[str] = None,
) -> Dict[str, Any]:
    """Which rules the fixtures exercise, and which they say nothing about.

    Read from the policy registry rather than from the fixtures, because the
    interesting set is the rules that have *no* fixture — and those, by
    definition, do not appear in any fixture to be counted.

    A rule with no fixture is indistinguishable from a working one on a green
    results page. Both of the rules that turned out to be broken in this
    repository were in exactly that position.
    """
    from app.services import policy_registry

    fixtures = load_fixtures(directory)
    if resource_type:
        fixtures = [f for f in fixtures if f.resource_type == resource_type]

    policies = policy_registry.load_policies()
    if policy_name:
        policies = [p for p in policies if p.name == policy_name]
    elif resource_type:
        policies = [p for p in policies if p.resource_type == resource_type]

    counts: Dict[str, Dict[str, Any]] = {}
    for fixture in fixtures:
        # A fixture that supplies data discovery cannot produce still proves the
        # rule's logic, but it proves nothing about whether the rule will ever
        # see that data in a real workspace. Both are tracked so the second
        # question can be asked separately.
        honest = not fixture.invented_fields
        for rule_id in set(fixture.fires) | set(fixture.passes):
            entry = counts.setdefault(
                rule_id, {"fires": [], "passes": [], "real_fires": []}
            )
            if rule_id in fixture.fires:
                entry["fires"].append(fixture.name)
                if honest:
                    entry["real_fires"].append(fixture.name)
            if rule_id in fixture.passes:
                entry["passes"].append(fixture.name)

    rules: List[Dict[str, Any]] = []
    for policy in policies:
        for rule in policy.rules:
            if not rule.id:
                continue
            entry = counts.get(rule.id, {"fires": [], "passes": [], "real_fires": []})
            rules.append(
                {
                    "rule_id": rule.id,
                    "title": rule.description or rule.rule,
                    "policy": policy.name,
                    "resource_type": policy.resource_type,
                    "fires_in": sorted(entry["fires"]),
                    "passes_in": sorted(entry["passes"]),
                    # Both directions matter. A rule only ever seen firing has
                    # never been shown to leave a compliant resource alone,
                    # which is how an over-broad rule gets missed.
                    "covered": bool(entry["fires"]),
                    "has_negative_case": bool(entry["passes"]),
                    # The rule has been shown to fire on a resource discovery
                    # could actually return. Without this, a fixture inventing a
                    # field turns a permanently dead rule into a green tick.
                    "reachable": bool(entry.get("real_fires")),
                }
            )

    covered = [r for r in rules if r["covered"]]
    reachable = [r for r in rules if r["reachable"]]
    return {
        "rules": sorted(rules, key=lambda r: r["rule_id"]),
        "total": len(rules),
        "covered": len(covered),
        "uncovered": len(rules) - len(covered),
        "reachable": len(reachable),
        # Covered by a fixture, but only one that supplies data the scanner
        # never produces. These are the rules that look tested and are dead.
        "only_synthetic": len(covered) - len(reachable),
        "fixture_count": len(fixtures),
        "fixtures_inventing_fields": sorted(
            f.name for f in fixtures if f.invented_fields
        ),
    }


# --- Capture ----------------------------------------------------------------


def _slugify(value: str) -> str:
    keep = [c if c.isalnum() else "_" for c in value.lower()]
    slug = "".join(keep).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug[:60] or "resource"


def capture_from_run(
    db,
    *,
    run_id: Optional[str] = None,
    resource_ids: Optional[List[str]] = None,
    limit: int = 25,
    directory: Optional[str] = None,
    anonymise: bool = True,
) -> List[Dict[str, Any]]:
    """Turn resources from a real scan into fixtures.

    Hand-written fixtures have one failure mode that matters: they drift from
    what the Databricks API actually returns, and then a rule passes its tests
    while missing the real thing. That is not hypothetical — the first run of
    this harness found a rule that never fired in production because the SDK
    sends ``null`` where the fixture author had assumed the key would be absent.

    Capturing removes the guesswork. ``sentinel_findings.data`` already holds
    the exact resource document each policy was evaluated against, so a fixture
    built from it is by construction the shape the API produced.

    The expectations are written from what actually happened, which makes a
    fresh capture a snapshot of current behaviour rather than of intended
    behaviour. That is the right default — it turns today's results into a
    regression test — but it means a captured fixture endorses whatever the
    policies do today, including any bug. Read it before committing it.
    """
    from app.db.sentinel_finding import SentinelFindingModel
    from app.db.sentinel_run import SentinelRunModel

    if run_id is None:
        latest = (
            db.query(SentinelRunModel.id)
            .order_by(SentinelRunModel.started_at.desc())
            .first()
        )
        if latest is None:
            return []
        run_id = latest[0]

    query = db.query(SentinelFindingModel).filter(
        SentinelFindingModel.run_id == run_id,
        SentinelFindingModel.kind.in_(("violation", "check")),
    )
    if resource_ids:
        query = query.filter(SentinelFindingModel.resource_id.in_(resource_ids))

    # Grouped by resource, because a fixture is one resource and every rule that
    # was evaluated against it. Taking one finding per fixture would produce
    # expectations that are silently incomplete, and an incomplete `fires` list
    # reads as "these rules should not have fired".
    by_resource: Dict[str, Dict[str, Any]] = {}
    for finding in query.all():
        snapshot = (finding.data or {}).get("resource")
        if not isinstance(snapshot, dict) or not snapshot.get("type"):
            continue

        key = str(finding.resource_id or snapshot.get("id") or "")
        if not key:
            continue

        entry = by_resource.setdefault(
            key,
            {
                "resource": snapshot,
                "workspace": finding.workspace,
                "environment": finding.environment or "prod",
                "fires": set(),
                "passes": set(),
                "name": snapshot.get("name") or key,
            },
        )

        rule_id = finding.policy_id or finding.rule_id
        if not rule_id:
            continue
        if finding.kind == "violation":
            entry["fires"].add(rule_id)
        else:
            entry["passes"].add(rule_id)

    directory = directory or fixtures_dir()
    os.makedirs(directory, exist_ok=True)

    written: List[Dict[str, Any]] = []
    for key, entry in list(by_resource.items())[:limit]:
        resource = dict(entry["resource"])
        workspace = entry["workspace"]

        if anonymise:
            # An owner's email address is the only thing in a resource snapshot
            # that identifies a person, and a fixture is a file in a repository
            # that anyone with read access can see.
            if resource.get("owner"):
                resource["owner"] = "owner@example.com"
            tags = resource.get("tags")
            if isinstance(tags, dict) and tags.get("owner"):
                resource = {**resource, "tags": {**tags, "owner": "owner@example.com"}}

        name = f"captured_{_slugify(str(entry['name']))}"
        payload = {
            "description": (
                f"Captured from run {run_id} — a real {resource.get('type')} as the "
                "API returned it. Expectations record what the policies did at "
                "capture time, not necessarily what they should do."
            ),
            "workspace": workspace,
            "environment": entry["environment"],
            "source": "captured",
            "resource": resource,
            "expect": {
                "fires": sorted(entry["fires"]),
                "passes": sorted(entry["passes"] - entry["fires"]),
            },
        }

        path = os.path.join(directory, f"{name}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, default=str)
            handle.write("\n")

        written.append(
            {
                "name": name,
                "resource_type": resource.get("type"),
                "fires": payload["expect"]["fires"],
                "passes": payload["expect"]["passes"],
            }
        )

    return written


async def run_all(
    directory: Optional[str] = None,
    *,
    only: Optional[List[str]] = None,
    resource_type: Optional[str] = None,
    draft: Optional[Draft] = None,
) -> Dict[str, Any]:
    """Run every fixture, or a subset of them, and summarise."""
    from app.core.config import settings
    from app.providers.opa.client import OpaProvider

    fixtures = load_fixtures(directory)
    if only:
        wanted = set(only)
        fixtures = [f for f in fixtures if f.name in wanted]
    if resource_type:
        fixtures = [f for f in fixtures if f.resource_type == resource_type]

    enforcement = bool(getattr(settings, "ENFORCEMENT_ENABLED", False))

    if not fixtures:
        return {
            "total": 0,
            "passed": 0,
            "failed": 0,
            # Not ok. Running no fixtures verifies nothing, and reporting that
            # as a pass is the same mistake as a CI step pointed at an empty
            # directory.
            "ok": False,
            "results": [],
            "enforcement_enabled": enforcement,
            "tested_draft": draft is not None,
        }

    opa = OpaProvider(settings.opa_provider_config())
    results = [await run_fixture(fixture, opa, draft) for fixture in fixtures]

    passed = sum(1 for r in results if r["passed"])
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "ok": passed == len(results),
        "results": results,
        # Surfaced because it explains why a rule that asks for WARN shows an
        # effective action of FLAG, which is otherwise the first thing anyone
        # asks about these results.
        "enforcement_enabled": enforcement,
        # So the UI can never quietly show committed-file results next to an
        # edited buffer and let someone believe their change was tested.
        "tested_draft": draft is not None,
    }
