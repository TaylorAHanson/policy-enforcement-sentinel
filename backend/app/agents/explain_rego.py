"""Rego to English, committed as a sibling ``.md``.

``policies/clusters.rego`` gets ``policies/clusters.md``. Committing the
explanation next to the policy means it is versioned by the same commit,
reviewed in the same pull request, and diffable — a reviewer who cannot read
Rego can still see that the English changed from "warns the owner" to "revokes
access", which is precisely the change worth catching.

Nothing here writes. Generation returns text; the pull request flow in
``api/v1/endpoints/policies.py`` commits it on the branch alongside the Rego, so
the two are always one commit apart from nothing. Reading is a plain filesystem
read of the working copy, which ``services/policy_sync.py`` keeps in step with
the target branch.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from app.agents import prompts
from app.services.agent_llm import AgentLLMClient

logger = logging.getLogger(__name__)


def explanation_path(policies_dir: str, policy_name: str) -> str:
    """The sibling ``.md`` for a policy file."""
    base = os.path.basename(policy_name)
    if base.endswith(".rego"):
        base = base[: -len(".rego")]
    return os.path.join(policies_dir, f"{base}.md")


def read_explanation(policy_name: str, policies_dir: Optional[str] = None) -> Optional[str]:
    """The committed explanation, if one exists."""
    if policies_dir is None:
        from app.core.config import settings

        policies_dir = settings.get_policies_dir

    path = explanation_path(policies_dir, policy_name)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return None


async def explain_rego(
    policy_name: str,
    content: str,
    *,
    llm: Optional[AgentLLMClient] = None,
) -> str:
    """Generate the plain-English version of a policy."""
    client = llm or AgentLLMClient()

    user = (
        f"Explain `{policy_name}`.\n\n```rego\n{content.strip()}\n```\n\n"
        "Remember: the first sentence is the consequence, in plain language."
    )
    text = await client.complete(
        prompts.EXPLANATION_SYSTEM_PROMPT, user, temperature=0.2
    )

    # Models sometimes fence Markdown output despite being asked not to.
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    return text


