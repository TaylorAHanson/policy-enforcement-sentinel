"""Pull request bodies for policy changes.

The interesting part is not the prose — it is the blast radius. A reviewer
looking at a diff cannot tell whether a tightened condition affects two clusters
or two hundred. The most recent scan can, so the numbers are computed here from
real findings and handed to the model as facts, rather than left for it to
estimate.

Tier escalation is detected structurally, from the parsed metadata of both
versions, and passed in as a finding the model is instructed to lead with. It is
not something the model is asked to notice.
"""
from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.agents import prompts
from app.agents.guardrails import inspect_generated_policy
from app.core.actions import TIER_LABELS, normalize_action, tier_of
from app.services.agent_llm import AgentLLMClient

logger = logging.getLogger(__name__)


@dataclass
class TierChange:
    """A rule whose requested action moved. Escalations lead the PR body."""

    rule: str
    old_action: str
    new_action: str
    old_tier: int
    new_tier: int

    @property
    def is_escalation(self) -> bool:
        return self.new_tier > self.old_tier

    def describe(self) -> str:
        direction = "raised" if self.is_escalation else "lowered"
        return (
            f"{self.rule}: {direction} from {self.old_action} "
            f"(Tier {self.old_tier}, {TIER_LABELS[self.old_tier]}) to "
            f"{self.new_action} (Tier {self.new_tier}, {TIER_LABELS[self.new_tier]})"
        )


@dataclass
class BlastRadius:
    """What the most recent scan says this policy currently touches."""

    run_id: Optional[int] = None
    total_findings: int = 0
    by_rule: Dict[str, int] = field(default_factory=dict)
    affected_owners: int = 0
    available: bool = True
    reason: str = ""

    def describe(self) -> str:
        if not self.available:
            return f"No blast-radius data: {self.reason}"
        if not self.total_findings:
            return "The most recent scan found nothing for this policy."

        lines = [
            f"The most recent scan (run {self.run_id}) produced "
            f"{self.total_findings} findings for this policy, across "
            f"{self.affected_owners} owners."
        ]
        for rule, count in sorted(self.by_rule.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {rule}: {count}")
        return "\n".join(lines)


def _rule_actions(content: str) -> Dict[str, str]:
    """Rule name -> requested action, read from ``rule_metadata``.

    Textual, matching :mod:`app.agents.guardrails`: comparing two versions of a
    policy means parsing a version that may not be saved, and evaluating unsaved
    Rego to diff it is a worse trade than a regex over a block whose shape the
    conventions fix.
    """
    import re

    actions: Dict[str, str] = {}
    # Matches `"rule_name": { ... "requested_action": "WARN" ... }` without
    # requiring the keys inside to be in any particular order.
    pattern = re.compile(
        r'"(\w+)"\s*:\s*\{(?:[^{}]|\{[^{}]*\})*?"requested_action"\s*:\s*"([^"]+)"',
        re.DOTALL,
    )
    for rule, action in pattern.findall(content):
        actions[rule] = normalize_action(action) or action
    return actions


def tier_changes(old_content: str, new_content: str) -> List[TierChange]:
    """Rules whose requested action moved between two versions."""
    old_actions = _rule_actions(old_content or "")
    new_actions = _rule_actions(new_content or "")

    changes: List[TierChange] = []
    for rule, new_action in new_actions.items():
        old_action = old_actions.get(rule)
        if old_action is None or old_action == new_action:
            continue
        changes.append(
            TierChange(
                rule=rule,
                old_action=old_action,
                new_action=new_action,
                old_tier=int(tier_of(old_action)),
                new_tier=int(tier_of(new_action)),
            )
        )
    # Escalations first, then by size of jump.
    changes.sort(key=lambda c: (not c.is_escalation, -(c.new_tier - c.old_tier)))
    return changes


def new_rules(old_content: str, new_content: str) -> List[str]:
    return sorted(set(_rule_actions(new_content)) - set(_rule_actions(old_content or "")))


def compute_blast_radius(policy_package: str) -> BlastRadius:
    """Findings for this policy in the most recent completed run."""
    from sqlalchemy import func

    from app.db.session import SessionLocal
    from app.db.sentinel_finding import SentinelFindingModel
    from app.db.sentinel_run import SentinelRunModel

    session = SessionLocal()
    try:
        run = (
            session.query(SentinelRunModel)
            .order_by(SentinelRunModel.id.desc())
            .first()
        )
        if run is None:
            return BlastRadius(available=False, reason="no scan has been run yet")

        rows = (
            session.query(
                SentinelFindingModel.rule_id,
                func.count(SentinelFindingModel.id),
            )
            .filter(
                SentinelFindingModel.run_id == run.id,
                SentinelFindingModel.policy == policy_package,
                SentinelFindingModel.kind == "violation",
            )
            .group_by(SentinelFindingModel.rule_id)
            .all()
        )

        owners = (
            session.query(func.count(func.distinct(SentinelFindingModel.owner)))
            .filter(
                SentinelFindingModel.run_id == run.id,
                SentinelFindingModel.policy == policy_package,
                SentinelFindingModel.kind == "violation",
            )
            .scalar()
        ) or 0

        by_rule = {rule or "(unnamed)": count for rule, count in rows}
        return BlastRadius(
            run_id=run.id,
            total_findings=sum(by_rule.values()),
            by_rule=by_rule,
            affected_owners=int(owners),
        )
    except Exception as e:
        logger.warning("Could not compute the blast radius for %s: %s", policy_package, e)
        return BlastRadius(available=False, reason=str(e))
    finally:
        session.close()


def unified_diff(old_content: str, new_content: str, policy_name: str) -> str:
    return "".join(
        difflib.unified_diff(
            (old_content or "").splitlines(keepends=True),
            (new_content or "").splitlines(keepends=True),
            fromfile=f"a/{policy_name}",
            tofile=f"b/{policy_name}",
            n=3,
        )
    )


async def pr_notes(
    policy_name: str,
    new_content: str,
    *,
    old_content: str = "",
    llm: Optional[AgentLLMClient] = None,
) -> dict:
    """Draft a PR body. Returns the text plus the facts it was built from.

    The structured fields come back alongside the prose so the PR path can fall
    back to a factual template if the model is unavailable — an unreviewed
    escalation reaching a PR body that does not mention it is the failure this
    function exists to prevent.
    """
    package = policy_name[: -len(".rego")] if policy_name.endswith(".rego") else policy_name

    changes = tier_changes(old_content, new_content)
    escalations = [c for c in changes if c.is_escalation]
    added = new_rules(old_content, new_content)
    radius = compute_blast_radius(package)
    report = inspect_generated_policy(new_content)

    facts = [f"Policy: {policy_name}"]
    if escalations:
        facts.append(
            "TIER ESCALATIONS (lead with these):\n"
            + "\n".join(f"  {c.describe()}" for c in escalations)
        )
    other_changes = [c for c in changes if not c.is_escalation]
    if other_changes:
        facts.append(
            "Other action changes:\n" + "\n".join(f"  {c.describe()}" for c in other_changes)
        )
    if added:
        facts.append("New rules: " + ", ".join(added))
    facts.append("Blast radius:\n" + radius.describe())
    facts.append(f"Highest tier requested anywhere in the file: {report.max_tier}")
    facts.append(
        "Diff:\n\n```diff\n" + (unified_diff(old_content, new_content, policy_name) or "(new file)") + "\n```"
    )

    body = ""
    try:
        client = llm or AgentLLMClient()
        body = await client.complete(
            prompts.PR_NOTES_SYSTEM_PROMPT,
            "\n\n".join(facts),
            temperature=0.2,
        )
    except Exception as e:
        logger.warning("Could not generate PR notes for %s: %s", policy_name, e)
        body = _fallback_body(policy_name, escalations, added, radius)

    return {
        "body": body,
        "escalations": [c.describe() for c in escalations],
        "action_changes": [c.describe() for c in changes],
        "new_rules": added,
        "blast_radius": {
            "run_id": radius.run_id,
            "total_findings": radius.total_findings,
            "by_rule": radius.by_rule,
            "affected_owners": radius.affected_owners,
            "available": radius.available,
        },
        "max_tier": report.max_tier,
    }


def _fallback_body(
    policy_name: str,
    escalations: List[TierChange],
    added: List[str],
    radius: BlastRadius,
) -> str:
    """A factual body for when the model is unavailable.

    Deliberately still leads with escalations. The assistant being switched off
    is not a reason for a reviewer to miss one.
    """
    parts = []
    if escalations:
        parts.append(
            "## Action tier raised\n\n"
            + "\n".join(f"- {c.describe()}" for c in escalations)
            + "\n\nThis change increases what the policy is permitted to do. "
            "Review it against the gates in `app/core/enforcement.py`."
        )
    parts.append(f"## What changed\n\nUpdates `{policy_name}`.")
    if added:
        parts.append("## Newly in scope\n\n" + "\n".join(f"- {rule}" for rule in added))
    parts.append("## Blast radius\n\n" + radius.describe())
    parts.append(
        "## Rolling back\n\nRevert this commit. Policy changes take effect on the "
        "next scan; nothing is applied retroactively."
    )
    return "\n\n".join(parts)
