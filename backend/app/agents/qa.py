"""Questions about the deployment, answered by looking things up.

The only capability that needs a loop. "Which of my clusters would be affected
if I raised CST-CLU-005 to THROTTLE?" cannot be answered from the question
alone — it needs the policy, the last scan's findings, and the current gate
settings, and which of those it needs depends on what the previous lookup
returned.

The loop is bounded by iteration count and wall clock, and every tool it can
reach is read-only by construction. See :mod:`app.agents.tools`.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from app.agents import prompts, tools as agent_tools
from app.services.agent_llm import AgentLLMClient, AgentResult, ChatMessage

logger = logging.getLogger(__name__)

#: How many prior turns to carry. Enough for a follow-up question to make sense
#: without the context growing until the tool results get squeezed out.
_MAX_HISTORY_TURNS = 8


def _history(turns: Optional[List[dict]]) -> List[ChatMessage]:
    if not turns:
        return []
    messages: List[ChatMessage] = []
    for turn in turns[-_MAX_HISTORY_TURNS:]:
        role = str(turn.get("role") or "").strip()
        content = str(turn.get("content") or "").strip()
        # Only plain user and assistant text is replayed. Rehydrating tool calls
        # from a client-supplied transcript would mean trusting the client's
        # account of what the tools returned.
        if role in {"user", "assistant"} and content:
            messages.append(ChatMessage(role=role, content=content))
    return messages


async def answer_question(
    question: str,
    *,
    history: Optional[List[dict]] = None,
    llm: Optional[AgentLLMClient] = None,
) -> AgentResult:
    """Answer a question about policies, findings, or enforcement."""
    client = llm or AgentLLMClient()

    result = await client.run_tool_loop(
        prompts.QA_SYSTEM_PROMPT,
        question.strip(),
        agent_tools.build_tools(),
        history=_history(history),
    )

    if result.truncated:
        logger.info(
            "Q&A loop was truncated after %d tool call(s).", len(result.tool_calls)
        )
    return result
