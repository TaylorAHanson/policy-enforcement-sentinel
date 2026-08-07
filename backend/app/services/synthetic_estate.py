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

import copy
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.enforcement import ActionRequest, ScanMode, resolve_effective_action

logger = logging.getLogger(__name__)

#: Where the shipped tests live: hand-written, generic, committed, and shipped
#: to every deployment. Under ``backend/`` so it syncs to the deployed app along
#: with everything else in there.
FIXTURES_DIRNAME = os.path.join("fixtures", "synthetic")

#: Where captures from a real scan land. Gitignored, local to whoever pressed
#: Capture, and never shipped.
#:
#: These two used to be one directory, which put files named after a customer's
#: catalogs and volumes into the same place as the generic ones and left them
#: sitting untracked in the git panel, one ``git add .`` from being published.
#: A capture is a snapshot of somebody's production estate; a shipped test is a
#: statement about the Databricks API. Keeping both in one directory meant every
#: capture had to be individually judged before any commit, forever.
CAPTURES_DIRNAME = os.path.join("fixtures", "captured")


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
    #: Loaded from the gitignored captures directory, so it exists on one
    #: machine and is not part of what ships. Set by the loader from the file's
    #: location, never from the file's contents.
    captured: bool = False

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


def _backend_root() -> str:
    from app.core.config import settings

    # Sibling of the policies directory's parent, i.e. backend/.
    return os.path.dirname(os.path.abspath(settings.get_policies_dir))


def fixtures_dir() -> str:
    """The committed, shipped tests."""
    from app.core.config import settings

    configured = getattr(settings, "SYNTHETIC_FIXTURES_DIR", None)
    if configured:
        return str(configured)
    return os.path.join(_backend_root(), FIXTURES_DIRNAME)


def captures_dir() -> str:
    """The local, gitignored captures."""
    from app.core.config import settings

    configured = getattr(settings, "CAPTURED_FIXTURES_DIR", None)
    if configured:
        return str(configured)
    return os.path.join(_backend_root(), CAPTURES_DIRNAME)


def _load_from(directory: str, *, captured: bool) -> List[Fixture]:
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
            fixture = parse_fixture(filename[: -len(".json")], payload)
            # The directory decides, not the file. A payload can claim any
            # source it likes, and what matters here is whether the file is one
            # git will publish.
            fixture.source = "captured" if captured else fixture.source
            fixture.captured = captured
            loaded.append(fixture)
        except (OSError, ValueError) as e:
            logger.warning("Skipping fixture %s: %s", filename, e)
    return loaded


def load_fixtures(
    directory: Optional[str] = None,
    *,
    include_captures: bool = True,
) -> List[Fixture]:
    """Every test on disk, sorted by name. A broken file is skipped, loudly.

    Both directories, because a capture is a real test and running it locally is
    the whole point of taking it. ``include_captures=False`` gives just the
    shipped set, which is what CI sees and what a coverage number should be
    quoted against — otherwise coverage rises on your laptop and nowhere else.

    An explicit ``directory`` reads only that one, for tests and for promotion.
    """
    if directory is not None:
        return _load_from(directory, captured=False)

    loaded = _load_from(fixtures_dir(), captured=False)
    if include_captures:
        loaded.extend(_load_from(captures_dir(), captured=True))
    return sorted(loaded, key=lambda f: f.name)


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

    # Shipped tests only. Captures are gitignored, so counting them would make
    # coverage higher on the laptop that took them than anywhere the app is
    # deployed, and a number that changes with who is looking at it is the kind
    # of thing this page exists to stop.
    fixtures = load_fixtures(directory, include_captures=False)
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


#: What a real owner's address is replaced with before a fixture is written.
ANONYMISED_OWNER = "owner@example.com"


def _is_personal(value: Any) -> bool:
    """Whether a value identifies a person and must not reach a fixture file.

    An address does. ``"unknown"`` does not — discovery writes it for a resource
    whose owner it could not determine, and it is precisely what the no-owner
    rules test for. Replacing it with a valid-looking address turns an unowned
    resource into an owned one, which silently inverts the expectation the
    capture recorded a moment earlier: a fixture asserting that the no-owner
    rule fires, on a resource that now has an owner.
    """
    return "@" in str(value or "")


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
    by_resource: Dict[tuple, Dict[str, Any]] = {}
    for finding in query.all():
        snapshot = (finding.data or {}).get("resource")
        if not isinstance(snapshot, dict) or not snapshot.get("type"):
            continue

        resource_id = str(finding.resource_id or snapshot.get("id") or "")
        if not resource_id:
            continue

        # Keyed by type *and* id. Ids are only unique within a type, and a real
        # workspace had `regression-validation-dev` as both an app and a
        # Lakebase instance. Keyed by id alone the two merged into one fixture:
        # the app's resource document carrying the union of both resources'
        # expectations, so it asserted that four Lakebase rules pass against an
        # app they never even run on.
        key = (str(snapshot.get("type")), resource_id)

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

    # The captures directory, not the shipped one. A capture is named after a
    # real catalog, schema and volume, and pressing this button should never put
    # a customer's resource names somewhere a later `git add .` would publish.
    directory = directory or captures_dir()
    os.makedirs(directory, exist_ok=True)

    written: List[Dict[str, Any]] = []
    for key, entry in list(by_resource.items())[:limit]:
        resource = dict(entry["resource"])
        workspace = entry["workspace"]

        if anonymise:
            # An owner's email address is the only thing in a resource snapshot
            # that identifies a person, and a fixture is a file in a repository
            # that anyone with read access can see.
            if _is_personal(resource.get("owner")):
                resource["owner"] = ANONYMISED_OWNER
            tags = resource.get("tags")
            if isinstance(tags, dict) and _is_personal(tags.get("owner")):
                resource = {**resource, "tags": {**tags, "owner": ANONYMISED_OWNER}}

        # The type is in the filename because two resources of different types
        # can share a name as readily as an id.
        name = f"captured_{_slugify(str(resource.get('type')))}_{_slugify(str(entry['name']))}"
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


# --- Promotion --------------------------------------------------------------
#
# A capture is worth keeping. What makes a rule fire in production is the exact
# shape the API returns — `"VolumeType.MANAGED"` where the policy compares
# against `"dbfs"`, `null` where the author assumed the key would be absent —
# and no amount of care writing fixtures by hand reproduces that. Every one of
# those mismatches this release found came from looking at real output.
#
# What is not worth keeping is the names. `scentre_group_raw_data` in catalog
# `psk` tells the next reader nothing about the API and quite a lot about a
# customer. So promotion keeps the shape and replaces the names, and then
# checks its own work rather than trusting that the list of keys below is
# complete.


#: Keys whose value names something real: a resource, a person, a place. The
#: value is replaced; the key, and the fact that it was a string, are kept.
IDENTIFYING_KEYS = frozenset(
    {
        "id",
        "name",
        "display_name",
        "resource_id",
        "catalog",
        "catalog_name",
        "schema",
        "schema_name",
        "table",
        "table_name",
        "owner",
        "creator",
        "creator_user_name",
        "user_name",
        "single_user_name",
        "run_as",
        "run_as_user_name",
        "email",
        "workspace",
        "workspace_name",
        "workspace_url",
        "host",
        "url",
        "path",
        "storage_location",
        "storage_root",
        "location",
        "cluster_name",
        "warehouse_name",
        "application_id",
        "service_principal_name",
    }
)

#: Substituted in, by key. Anything not listed gets ``<key>-1``.
PLACEHOLDERS = {
    "catalog": "main",
    "catalog_name": "main",
    "schema": "analytics",
    "schema_name": "analytics",
    "owner": ANONYMISED_OWNER,
    "creator": ANONYMISED_OWNER,
    "creator_user_name": ANONYMISED_OWNER,
    "user_name": ANONYMISED_OWNER,
    "run_as": ANONYMISED_OWNER,
    "run_as_user_name": ANONYMISED_OWNER,
    "email": ANONYMISED_OWNER,
    "workspace": "ws-enterprise-prod",
    "workspace_name": "ws-enterprise-prod",
}

#: Values that mean "no value" and must survive promotion untouched. Replacing
#: these is the bug from the capture anonymiser all over again: an unowned
#: resource quietly gains an owner and the no-owner expectation it was captured
#: to prove inverts.
SENTINEL_VALUES = frozenset({"unknown", "none", "n/a", "null", ""})


def _placeholder_for(key: str, index: int) -> str:
    if key in PLACEHOLDERS:
        return PLACEHOLDERS[key]
    return f"{key.replace('_', '-')}-{index}"


def _identifying_tokens(value: Any) -> List[str]:
    """The words in a value that would identify something if they survived.

    Split on separators because a real id is a compound of other names:
    ``psk.genie_space_optimizer.scentre_group_raw_data`` is a catalog, a schema
    and a volume in one string. Replacing the ``id`` key alone leaves the same
    three names sitting in ``catalog``, ``schema`` and ``name``, and replacing
    those three leaves them inside the id.
    """
    text = str(value or "")
    tokens: List[str] = []
    for part in re.split(r"[./:\\\-_@\s]+", text):
        part = part.strip().lower()
        # Short parts produce false positives against words like "prod" or "id"
        # that legitimately appear in placeholder text.
        if len(part) >= 4 and part not in SENTINEL_VALUES:
            tokens.append(part)
    return tokens


def scrub(payload: Dict[str, Any]) -> Dict[str, Any]:
    """A captured test with the names replaced and the shape kept.

    Returns the new payload plus what was replaced and anything suspicious that
    survived, so promotion can be reviewed rather than trusted.
    """
    original = copy.deepcopy(payload)
    scrubbed = copy.deepcopy(payload)

    replacements: List[Dict[str, str]] = []
    counter: Dict[str, int] = {}

    def walk(node: Any, path: str = "") -> Any:
        if isinstance(node, dict):
            return {k: walk(v, f"{path}.{k}" if path else k) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, f"{path}[]") for v in node]
        if not isinstance(node, str):
            # Numbers, booleans and nulls are shape, never identity. `null` in
            # particular is the single most valuable thing a capture carries.
            return node

        key = path.rsplit(".", 1)[-1].removesuffix("[]")
        keep = node.strip().lower() in SENTINEL_VALUES
        if keep:
            return node

        if key in IDENTIFYING_KEYS or "@" in node:
            counter[key] = counter.get(key, 0) + 1
            # An address is replaced with an address, whatever key it arrived
            # under. Swapping it for `some-new-field-1` would remove the name
            # and also the fact that the value was an email, and a rule reading
            # an owner field is quite likely to care about the difference.
            new = (
                ANONYMISED_OWNER
                if "@" in node
                else _placeholder_for(key, counter[key])
            )
            replacements.append({"path": path, "from": node, "to": new})
            return new
        return node

    scrubbed["resource"] = walk(scrubbed.get("resource") or {}, "")
    scrubbed["workspace"] = PLACEHOLDERS["workspace"]
    _rebuild_compound_id(original.get("resource") or {}, scrubbed["resource"])

    # `owner` is already `owner@example.com` on anything captured, so reporting
    # it as a replacement is noise in a list whose whole job is to be read.
    replacements = [r for r in replacements if r["from"] != r["to"]]

    # The description carries the run id, which is not identifying on its own
    # but points at a specific scan of a specific estate.
    scrubbed["description"] = (
        f"A real {(scrubbed.get('resource') or {}).get('type')} as the Databricks API "
        "returns it, with the names replaced. The shape is the point: the exact "
        "spellings, the nulls, and which keys arrive at all."
    )
    scrubbed["source"] = "promoted"

    return {
        "payload": scrubbed,
        "replacements": replacements,
        "survivors": _survivors(original, scrubbed),
    }


#: Ids built by joining other fields with a dot, per resource type's convention.
#: Unity Catalog's three-level name is the one that matters here.
COMPOUND_ID_PARTS = ("catalog", "schema", "name")


def _rebuild_compound_id(original: Dict[str, Any], scrubbed: Dict[str, Any]) -> None:
    """Keep a dotted id dotted.

    A Unity Catalog id is ``catalog.schema.name``, and scrubbing it as one
    opaque string turns it into ``id-1``. That reads fine and quietly discards a
    real structural property: any rule that splits an id on dots, or any handler
    change that starts producing two levels instead of three, would be tested
    against a value that no longer has the shape the API produces.

    Only rewrites when the original id genuinely was its parts joined, so a
    resource type whose id follows some other convention is left alone.
    """
    old_id = original.get("id")
    if not isinstance(old_id, str) or "." not in old_id:
        return

    old_parts = [original.get(p) for p in COMPOUND_ID_PARTS]
    if not all(isinstance(p, str) and p for p in old_parts):
        return
    if old_id != ".".join(str(p) for p in old_parts):
        return

    new_parts = [scrubbed.get(p) for p in COMPOUND_ID_PARTS]
    if all(isinstance(p, str) and p for p in new_parts):
        scrubbed["id"] = ".".join(str(p) for p in new_parts)


def _survivors(original: Dict[str, Any], scrubbed: Dict[str, Any]) -> List[Dict[str, str]]:
    """Identifying words from the original that are still in the scrubbed copy.

    The point of this function is that :data:`IDENTIFYING_KEYS` is a guess. It
    was written against the handlers that exist today, and the next handler will
    emit a key nobody added to it. Rather than find that out when a customer's
    catalog name appears in a pull request, promotion checks whether any word it
    set out to remove is still present, and refuses to be silent about it.
    """
    wanted: set = set()
    for key in IDENTIFYING_KEYS:
        for value in _values_at(original, key):
            wanted.update(_identifying_tokens(value))
    for value in [original.get("workspace")]:
        wanted.update(_identifying_tokens(value))

    # Placeholders are made of ordinary words and would otherwise match.
    for placeholder in set(PLACEHOLDERS.values()):
        wanted.difference_update(_identifying_tokens(placeholder))

    # So is the resource type, which is a fixed vocabulary the handler sets and
    # never anything a customer chose. A warehouse named "Serverless Starter
    # Warehouse" put "warehouse" on the wanted list and the check then flagged
    # `type: sql_warehouse` as a leak, refusing to promote a capture that gives
    # away nothing. A false refusal here is not harmless: it teaches people that
    # the block is noise, which is the last thing a safety check can afford.
    wanted.difference_update(
        _identifying_tokens((scrubbed.get("resource") or {}).get("type"))
    )

    found: List[Dict[str, str]] = []
    for path, value in _strings(scrubbed.get("resource") or {}):
        for token in _identifying_tokens(value):
            if token in wanted:
                found.append({"path": path, "value": value, "token": token})
                break
    return found


def _values_at(node: Any, key: str) -> List[Any]:
    out: List[Any] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key and isinstance(v, str):
                out.append(v)
            out.extend(_values_at(v, key))
    elif isinstance(node, list):
        for v in node:
            out.extend(_values_at(v, key))
    return out


def _strings(node: Any, path: str = "") -> List[tuple]:
    out: List[tuple] = []
    if isinstance(node, dict):
        for k, v in node.items():
            out.extend(_strings(v, f"{path}.{k}" if path else k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out.extend(_strings(v, f"{path}[{i}]"))
    elif isinstance(node, str):
        out.append((path, node))
    return out


def plan_promotion(
    name: str,
    *,
    directory: Optional[str] = None,
    taken: Optional[set] = None,
) -> Dict[str, Any]:
    """What promoting this capture would write, without writing it.

    ``taken`` lets a caller planning several at once avoid proposing one name
    twice, which the list endpoint needs: six apps breaking the same rule would
    otherwise all show the same target and five of them would fail on press.
    """
    source_dir = directory or captures_dir()
    path = os.path.join(source_dir, f"{name}.json")
    if not os.path.isfile(path):
        raise FixtureError(f"No capture named {name}.")

    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    result = scrub(payload)
    result["name"] = name
    result["target_name"] = _promoted_name(result["payload"], taken=taken)
    result["withheld"] = _withhold_broken_endorsements(result["payload"])
    return result


def _withhold_broken_endorsements(payload: Dict[str, Any]) -> List[str]:
    """Drop `passes` entries for rules already known not to work. Mutates.

    A capture records what the policies did, so a rule that is broken shows up
    as one that passed, and promoting that writes a committed test asserting the
    broken rule is fine. The first capture promoted here did exactly that: it
    vouched for ``SEC-VOL-001``, which compares ``storage_type`` against
    ``"dbfs"`` while the API sends ``"VolumeType.MANAGED"`` and therefore cannot
    fire at all.

    A green tick is read as evidence, and this is the whole failure this harness
    exists to prevent — so the endorsement is withheld rather than the promotion
    refused. The test keeps everything it genuinely demonstrates and simply says
    nothing about the broken rule, which leaves that rule visibly untested,
    which is the truth.
    """
    from app.services import rule_diagnosis

    try:
        diagnosis = rule_diagnosis.diagnose()
    except Exception as e:  # pragma: no cover - diagnosis is advisory here
        logger.warning("Could not check promoted expectations against diagnosis: %s", e)
        return []

    broken = {
        str(r["rule_id"])
        for r in diagnosis.get("rules", [])
        if r.get("category") == "suspect"
    }
    expect = payload.get("expect") or {}
    passes = [str(r) for r in expect.get("passes") or []]

    withheld = [r for r in passes if r in broken]
    if withheld:
        expect["passes"] = [r for r in passes if r not in broken]
    return withheld


def _promoted_name(payload: Dict[str, Any], *, taken: Optional[set] = None) -> str:
    """Named for what it demonstrates, since it is no longer named for a resource.

    Six apps in one workspace break the same rule, so six captures want the same
    name. They are still six different resource documents and worth keeping
    apart, so the name gets a suffix rather than the promotion being refused —
    ``taken`` is what already exists plus what a caller has already planned.
    """
    resource_type = _slugify(str((payload.get("resource") or {}).get("type") or "resource"))
    fires = [str(r) for r in (payload.get("expect") or {}).get("fires") or []]
    base = f"real_{resource_type}_{_slugify(fires[0])}" if fires else f"real_{resource_type}_shape"

    taken = taken if taken is not None else _shipped_names()
    if base not in taken:
        return base
    n = 2
    while f"{base}_{n}" in taken:
        n += 1
    return f"{base}_{n}"


def _names_in(directory: str) -> set:
    if not os.path.isdir(directory):
        return set()
    return {f[: -len(".json")] for f in os.listdir(directory) if f.endswith(".json")}


def _shipped_names() -> set:
    return _names_in(fixtures_dir())


async def verify_scrub(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Whether the scrubbed test still does what the capture recorded.

    Scrubbing edits the document the policies read, so it can change the answer.
    A rule matching a naming convention, or reading a catalog against an
    allowlist, evaluates differently once the names are placeholders — and the
    failure mode is a test that still passes while no longer demonstrating
    anything, which is the exact thing this harness exists to catch.

    So the scrubbed copy is run before it is written, and its real behaviour is
    compared to what the capture recorded a moment earlier.
    """
    from app.core.config import settings
    from app.providers.opa.client import OpaProvider

    fixture = parse_fixture("promotion-check", payload)
    opa = OpaProvider(settings.opa_provider_config())
    result = await run_fixture(fixture, opa)

    return {
        "passed": bool(result.get("passed")),
        "error": result.get("error"),
        # Rules that fired but were not expected to, and vice versa.
        "unexpected": result.get("unexpected") or [],
        "missing": result.get("missing") or [],
    }


async def promote(
    name: str,
    *,
    directory: Optional[str] = None,
    target_directory: Optional[str] = None,
    target_name: Optional[str] = None,
    allow_survivors: bool = False,
    verify: bool = True,
) -> Dict[str, Any]:
    """Move a capture into the shipped set, with the names taken out.

    Refuses on two conditions, both fail-closed. Promotion is the one path from
    a real estate into a committed file, so it says which value it is unhappy
    about rather than writing the file and mentioning it in a field nobody reads.

    First, when the residual check finds an identifying word still present.
    Second, when scrubbing changed what the policies do to the resource, which
    means the promoted test would no longer demonstrate what it was taken for.
    """
    # Uniqueness is checked against the directory being written to, not against
    # the default one, so a caller promoting somewhere else gets names that are
    # unique there.
    target_dir = target_directory or fixtures_dir()
    plan = plan_promotion(name, directory=directory, taken=_names_in(target_dir))

    if plan["survivors"] and not allow_survivors:
        paths = ", ".join(sorted({s["path"] for s in plan["survivors"]}))
        raise FixtureError(
            f"Not promoting {name}: identifying values survived scrubbing at {paths}. "
            "Add the key to IDENTIFYING_KEYS, or edit the capture by hand first."
        )

    verification = None
    if verify:
        verification = await verify_scrub(plan["payload"])
        if not verification["passed"]:
            changed = ", ".join(
                sorted(set(verification["unexpected"]) | set(verification["missing"]))
            )
            raise FixtureError(
                f"Not promoting {name}: replacing the names changed what the policies "
                f"do to it ({changed or verification['error']}). The promoted test "
                "would no longer show what the capture was taken to show."
            )

    os.makedirs(target_dir, exist_ok=True)

    final_name = target_name or plan["target_name"]
    target_path = os.path.join(target_dir, f"{final_name}.json")
    if os.path.exists(target_path):
        raise FixtureError(f"{final_name} already exists in the shipped tests.")

    with open(target_path, "w", encoding="utf-8") as handle:
        json.dump(plan["payload"], handle, indent=2, default=str)
        handle.write("\n")

    return {
        "name": final_name,
        "path": target_path,
        "replacements": plan["replacements"],
        "survivors": plan["survivors"],
        "withheld": plan["withheld"],
        "verification": verification,
    }


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
