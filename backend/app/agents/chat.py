"""One conversation that both answers and edits.

This replaces a split that never made sense to the person using it. Authoring
was a one-shot code generator whose prompt forbade prose, so asking it a
question got you a policy file; Q&A was a separate tab that could read policies
and not change them. A user who asked "why does CST-CLU-005 fire on this
cluster, and can you relax it?" had to ask twice, in two places, and join the
answers up themselves.

So the loop here is the Q&A loop — same read-only tools, same bounds — with one
addition: the reply may end with a fenced ``rego`` block, which is lifted out
and returned separately as a proposal. Prose is the default and the block is
optional, which is the opposite of what authoring did.

Nothing here writes. A proposal goes back to the editor as a diff, and a human
decides whether to take it and open a pull request.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

from app.agents import author_rego, prompts, tools as agent_tools
from app.agents.guardrails import GuardrailViolation, check_generated_policy
from app.services.agent_llm import AgentLLMClient, ChatMessage, ToolInvocation

logger = logging.getLogger(__name__)

#: How many prior turns to carry, matching the Q&A loop.
_MAX_HISTORY_TURNS = 8

#: A fenced block, with the fence kept so it can be cut out of the prose.
_FENCE = re.compile(r"```[ \t]*rego[ \t]*\n(.*?)```", re.DOTALL | re.IGNORECASE)

#: A proposal is a whole file, and a whole file declares a package. Requiring
#: this is what stops an illustrative snippet — fenced as rego while the model
#: explains itself — from being diffed against the open file as though it were
#: the replacement, which would read as deleting everything it left out.
_PACKAGE = re.compile(r"^\s*package\s+[\w.]+", re.MULTILINE)


@dataclass
class ChatReply:
    """What the assistant said, and what it wants to change."""

    answer: str
    proposal: Optional[author_rego.AuthoredPolicy] = None
    #: Set when a proposal was withdrawn by the guardrails. The prose survives:
    #: the model's explanation of what it was trying to do is still worth
    #: reading, and is usually where the user finds out why it was refused.
    refusal: Optional[dict] = None
    #: Fields the proposal reads that discovery never collects. Not a refusal:
    #: the policy is valid and safe, it just cannot ever fire, which is a thing
    #: the reviewer needs told rather than a thing to block on.
    field_warnings: List[dict] = field(default_factory=list)
    tool_calls: List[ToolInvocation] = field(default_factory=list)
    truncated: bool = False

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "proposal": self.proposal.to_dict() if self.proposal else None,
            "refusal": self.refusal,
            "field_warnings": self.field_warnings,
            "truncated": self.truncated,
            "tool_calls": [
                {"tool": call.tool, "arguments": call.arguments, "error": call.error}
                for call in self.tool_calls
            ],
        }


def split_proposal(reply: str) -> tuple[str, Optional[str]]:
    """Separate the prose from a proposed file.

    Returns ``(prose, rego)``. The last qualifying block wins: the protocol asks
    for the file at the end, and if a model emits two, the later one is the one
    it settled on.
    """
    candidates = [
        match for match in _FENCE.finditer(reply) if _PACKAGE.search(match.group(1))
    ]
    if not candidates:
        return reply.strip(), None

    chosen = candidates[-1]
    prose = (reply[: chosen.start()] + reply[chosen.end() :]).strip()
    return prose, chosen.group(1).strip()


def _history(turns: Optional[List[dict]]) -> List[ChatMessage]:
    if not turns:
        return []
    messages: List[ChatMessage] = []
    for turn in turns[-_MAX_HISTORY_TURNS:]:
        role = str(turn.get("role") or "").strip()
        content = str(turn.get("content") or "").strip()
        # Only plain text is replayed, for the same reason as the Q&A loop:
        # rehydrating tool calls from a client-supplied transcript would mean
        # trusting the client's account of what the tools returned.
        if role in {"user", "assistant"} and content:
            messages.append(ChatMessage(role=role, content=content))
    return messages


def _resource_type(policy_name: Optional[str]) -> Optional[str]:
    """The resource type of the open policy, if it is a known one."""
    if not policy_name:
        return None
    try:
        from app.services import policy_registry

        descriptor = policy_registry.get_policy(policy_name)
        return descriptor.resource_type if descriptor else None
    except Exception as e:
        # Losing the scoping means a larger prompt, not a wrong one.
        logger.debug("Could not resolve resource type for %s: %s", policy_name, e)
        return None


async def _repair(
    client: AgentLLMClient,
    content: str,
    errors: List[str],
    target_policy: Optional[str],
) -> tuple[str, List[str]]:
    """One attempt at fixing a draft that did not compile.

    A model handed the compiler error usually fixes it first try; a second
    attempt rarely converges and doubles how long the user waits to be told it
    failed. Same budget as the authoring path, for the same reason.
    """
    prompt = (
        "This policy did not compile. `opa check` reported:\n\n"
        + "\n".join(errors)
        + f"\n\nHere is the file:\n\n```rego\n{content}\n```\n\n"
        "Return the corrected file as a single fenced rego block and nothing else."
    )
    response = await client.complete(prompts.authoring_system_prompt(), prompt)
    repaired = author_rego.extract_rego(response)
    if not repaired:
        return content, errors

    remaining = await author_rego.check_rego(
        repaired, author_rego.proposal_filename(repaired, target_policy)
    )
    return repaired, remaining


async def chat(
    message: str,
    *,
    history: Optional[List[dict]] = None,
    target_policy: Optional[str] = None,
    open_content: Optional[str] = None,
    llm: Optional[AgentLLMClient] = None,
) -> ChatReply:
    """Answer, and propose an edit if one was asked for.

    ``target_policy`` and ``open_content`` are what the user is looking at. They
    are context, not a command: a question about an open file still gets an
    answer rather than a rewrite of it.
    """
    client = llm or AgentLLMClient()

    request = [message.strip()]
    if target_policy:
        request.append(
            f"\nThe user currently has `{target_policy}` open in the editor."
        )
        if open_content:
            request.append(
                "Its current contents, which is what any change you propose must "
                f"be based on:\n\n```rego\n{open_content.strip()}\n```"
            )
    user = "\n".join(request)

    # Scoped to the open policy's type when there is one. The full catalogue is
    # every field of thirteen resource types, and the handful that matter get
    # lost in it — which is the failure mode the catalogue exists to prevent.
    result = await client.run_tool_loop(
        prompts.chat_system_prompt(resource_type=_resource_type(target_policy)),
        user,
        agent_tools.build_tools(),
        history=_history(history),
    )

    if result.truncated:
        logger.info(
            "Chat loop was truncated after %d tool call(s).", len(result.tool_calls)
        )

    prose, rego = split_proposal(result.answer)
    reply = ChatReply(
        answer=prose,
        tool_calls=result.tool_calls,
        truncated=result.truncated,
    )

    if rego is None:
        return reply

    def withdraw(e: GuardrailViolation) -> ChatReply:
        # Refused rather than repaired. Rewriting DELETE to WARN would hand back
        # a policy that does something other than what it says, under a name
        # that suggests otherwise.
        logger.warning("Withdrew a proposed policy: %s", e)
        reply.refusal = e.to_dict()
        return reply

    try:
        # The tier ceiling is checked before anything is spent on validating the
        # draft, and long before the user sees a diff they might accept.
        report = check_generated_policy(rego)
    except GuardrailViolation as e:
        return withdraw(e)

    errors = await author_rego.check_rego(
        rego, author_rego.proposal_filename(rego, target_policy)
    )
    attempts = 1

    if errors and not errors[0].startswith("Could not run `opa check`"):
        logger.info("Proposed Rego failed validation; repairing once. %s", errors)
        rego, errors = await _repair(client, rego, errors, target_policy)
        attempts = 2
        try:
            # The repair is model output too, so it faces the same ceiling.
            report = check_generated_policy(rego)
        except GuardrailViolation as e:
            return withdraw(e)

    reply.proposal = author_rego.build_proposal(
        rego,
        target_policy=target_policy,
        errors=errors,
        guardrails=report,
        attempts=attempts,
    )

    # Attached rather than refused. A field the scanner does not collect makes a
    # rule inert, not dangerous, and the reviewer is better placed than this
    # code to judge whether the field is genuinely absent or the annotation is
    # just wrong. But it has to be *said*, because the failure it describes is
    # completely silent afterwards.
    try:
        from app.services import resource_schema

        reply.field_warnings = resource_schema.check_fields(
            rego, _resource_type(target_policy) or _declared_resource_type(rego)
        )
    except Exception as e:
        logger.debug("Field check on a proposal failed: %s", e)

    return reply


def _declared_resource_type(content: str) -> Optional[str]:
    """The resource type a draft claims, for a policy with no registry entry."""
    match = re.search(r"resource_type:\s*([a-zA-Z_][a-zA-Z0-9_]*)", content)
    return match.group(1) if match else None
