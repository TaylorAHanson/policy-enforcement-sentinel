"""Natural language to Rego.

Two things happen to the model's output before anyone sees it:

1. It is validated with ``opa check`` against a copy of the real policies
   directory, so cross-file imports resolve exactly as they will after a save.
   A syntax failure is fed back once, because a model given the compiler error
   usually fixes it and giving it more attempts mostly produces slower failure.
2. It is checked for tier and destructiveness by :mod:`app.agents.guardrails`,
   which does not trust the prompt.

The result is never written to disk. It goes back to the editor as a proposal,
and a human saves it.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

from app.agents import prompts
from app.agents.guardrails import GuardrailReport, check_generated_policy
from app.services.agent_llm import AgentLLMClient

logger = logging.getLogger(__name__)

_FENCE_PATTERN = re.compile(r"```(?:rego)?\s*\n(.*?)```", re.DOTALL)
_PACKAGE_PATTERN = re.compile(r"^\s*package\s+([\w.]+)", re.MULTILINE)

#: One retry. The first repair attempt fixes most syntax errors; a second rarely
#: converges and doubles the time the user waits for a failure.
_MAX_VALIDATION_ATTEMPTS = 2


@dataclass
class AuthoredPolicy:
    """A proposal. Nothing has been written."""

    content: str
    policy_name: str
    package: str
    is_new_file: bool
    valid: bool
    validation_errors: List[str] = field(default_factory=list)
    guardrails: Optional[GuardrailReport] = None
    attempts: int = 1

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "policy_name": self.policy_name,
            "package": self.package,
            "is_new_file": self.is_new_file,
            "valid": self.valid,
            "validation_errors": self.validation_errors,
            "attempts": self.attempts,
            "max_tier": self.guardrails.max_tier if self.guardrails else 0,
            "requested_actions": sorted(set(self.guardrails.actions)) if self.guardrails else [],
        }


def extract_rego(response: str) -> str:
    """Pull the Rego out of the reply.

    The prompt asks for a bare fenced block, and the model usually complies, but
    "usually" is not a parsing strategy.
    """
    match = _FENCE_PATTERN.search(response)
    if match:
        return match.group(1).strip()
    return response.strip()


def _package_of(content: str) -> str:
    match = _PACKAGE_PATTERN.search(content)
    if not match:
        return ""
    path = match.group(1)
    prefix = "databricks.governance."
    return path[len(prefix):] if path.startswith(prefix) else path.rsplit(".", 1)[-1]


async def author_rego(
    instruction: str,
    *,
    target_policy: Optional[str] = None,
    existing_content: Optional[str] = None,
    llm: Optional[AgentLLMClient] = None,
) -> AuthoredPolicy:
    """Draft a policy from a natural-language description.

    ``target_policy`` and ``existing_content`` scope the request to one file,
    which is what the editor sends when the user is adding a rule to a policy
    they already have open.

    Raises :class:`app.agents.guardrails.GuardrailViolation` if the model asks
    for more than Tier 2.
    """
    from app.core.config import settings
    from app.providers.opa.client import OpaProvider

    client = llm or AgentLLMClient()
    system = prompts.authoring_system_prompt()

    request = [f"Request: {instruction.strip()}"]
    if target_policy:
        request.append(f"\nPut this in `{target_policy}` unless it clearly belongs elsewhere.")
    if existing_content:
        request.append(
            "\nThe current contents of that file, which you should return with "
            f"your change applied:\n\n```rego\n{existing_content.strip()}\n```"
        )
    user = "\n".join(request)

    opa = OpaProvider(settings.opa_provider_config())
    errors: List[str] = []
    content = ""
    attempt = 0

    for attempt in range(1, _MAX_VALIDATION_ATTEMPTS + 1):
        response = await client.complete(system, user, temperature=0.1)
        content = extract_rego(response)

        if not content:
            errors = ["The assistant returned an empty policy."]
            break

        package = _package_of(content)
        candidate_name = target_policy or (f"{package}.rego" if package else "generated.rego")
        if not candidate_name.endswith(".rego"):
            candidate_name += ".rego"

        try:
            result = await opa.check(candidate_name, content)
        except Exception as e:
            logger.warning("Could not validate generated Rego: %s", e)
            # An unavailable OPA binary is an environment problem, not a problem
            # with the policy. Returning the draft unvalidated, clearly marked,
            # beats refusing to show the user anything.
            errors = [f"Could not run `opa check`: {e}"]
            break

        if result.get("valid"):
            errors = []
            break

        errors = [str(e) for e in (result.get("errors") or ["unknown validation error"])]
        if attempt < _MAX_VALIDATION_ATTEMPTS:
            logger.info("Generated Rego failed validation; retrying once. %s", errors)
            user = (
                f"{user}\n\nYour previous attempt did not compile. `opa check` "
                f"reported:\n\n{chr(10).join(errors)}\n\nHere is what you produced:\n\n"
                f"```rego\n{content}\n```\n\nReturn the corrected file."
            )

    # Runs on the final draft whether or not it compiled. A policy that fails to
    # compile but requests DELETE is still a policy that requested DELETE, and
    # the user should be told that rather than shown a syntax error.
    report = check_generated_policy(content)

    package = _package_of(content)
    policy_name = target_policy or (f"{package}.rego" if package else "generated.rego")
    if not policy_name.endswith(".rego"):
        policy_name += ".rego"

    return AuthoredPolicy(
        content=content,
        policy_name=policy_name,
        package=package,
        is_new_file=_is_new_file(policy_name),
        valid=not errors,
        validation_errors=errors,
        guardrails=report,
        attempts=attempt,
    )


def _is_new_file(policy_name: str) -> bool:
    import os

    from app.core.config import settings

    return not os.path.exists(os.path.join(settings.get_policies_dir, policy_name))
