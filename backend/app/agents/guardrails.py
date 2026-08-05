"""Post-generation safety checks on model-authored Rego.

The prompt tells the model it may only emit Tier 0-2 actions. This module
assumes it did not listen.

A model is not a gate. Prompt instructions are a strong prior and nothing more,
and the failure mode here — a policy that quietly requests DELETE — is exactly
the one the whole safety model exists to prevent. So the tier ceiling is
enforced here, on the generated text, without reference to what the prompt said.

Violations are rejected outright rather than repaired. Silently rewriting
``DELETE`` to ``WARN`` would produce a policy that does something other than
what the user asked for, under a name that suggests otherwise. Refusing, and
saying that a Tier 3 action has to be written by hand in a reviewed PR, keeps
the human in the loop at the point where the decision actually matters.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

from app.core.actions import ACTIONS, ActionTier, normalize_action, tier_of

#: The highest tier a generated policy may request. Tier 2 (RESTRICT) is
#: reversible by construction — every action at that tier has an undo method —
#: which is what makes it safe to generate. Tier 3 is not.
MAX_GENERATED_TIER = ActionTier.RESTRICT

_ACTION_PATTERN = re.compile(r'"requested_action"\s*:\s*"([^"]*)"')
_DESTRUCTIVE_PATTERN = re.compile(r'"destructive"\s*:\s*(true|false)')


class GuardrailViolation(Exception):
    """Generated Rego asked for more power than the assistant may grant.

    Carries the specific violations so the UI can explain what to do instead,
    rather than showing a generic refusal.
    """

    def __init__(self, violations: List[str]):
        self.violations = violations
        super().__init__("; ".join(violations))

    def to_dict(self) -> dict:
        return {
            "error": "guardrail_violation",
            "violations": self.violations,
            "remedy": (
                "The assistant only writes policies up to Tier 2 (RESTRICT), which "
                "is reversible. A policy that deletes or terminates a resource has "
                "to be written by hand and go through a reviewed pull request."
            ),
        }


@dataclass
class GuardrailReport:
    """What the generated policy asked for. Useful even when it passes."""

    actions: List[str]
    max_tier: int
    declares_destructive: bool
    violations: List[str]

    @property
    def ok(self) -> bool:
        return not self.violations


def inspect_generated_policy(content: str) -> GuardrailReport:
    """Read the tier and destructive claims out of generated Rego.

    Deliberately textual. The alternative — evaluating the policy to read its
    ``rule_metadata`` — means running model-authored code to decide whether
    model-authored code is safe to run, and a text scan cannot be talked into
    returning the wrong answer by the thing it is scanning.
    """
    violations: List[str] = []
    actions: List[str] = []
    max_tier = 0

    for raw in _ACTION_PATTERN.findall(content):
        actions.append(raw)
        normalized = normalize_action(raw)

        if normalized is None:
            violations.append(
                f"requested_action {raw!r} is not a known action. Valid actions are: "
                f"{', '.join(sorted(ACTIONS))}."
            )
            continue

        tier = tier_of(normalized)
        max_tier = max(max_tier, int(tier))
        if tier > MAX_GENERATED_TIER:
            violations.append(
                f"requested_action {normalized!r} is Tier {int(tier)}, above the "
                f"Tier {int(MAX_GENERATED_TIER)} ceiling for generated policies."
            )

    declares_destructive = "true" in _DESTRUCTIVE_PATTERN.findall(content)
    if declares_destructive:
        violations.append(
            "The policy declares `destructive: true`. A destructive policy has to "
            "be written by hand."
        )

    return GuardrailReport(
        actions=actions,
        max_tier=max_tier,
        declares_destructive=declares_destructive,
        violations=violations,
    )


def check_generated_policy(content: str) -> GuardrailReport:
    """Raise :class:`GuardrailViolation` if the policy exceeds the ceiling."""
    report = inspect_generated_policy(content)
    if not report.ok:
        raise GuardrailViolation(report.violations)
    return report
