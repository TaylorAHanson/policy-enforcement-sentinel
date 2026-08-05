"""The agent's interface to the model.

Two shapes of call, and the distinction is deliberate:

* :meth:`AgentLLMClient.complete` — one request, one answer. Used for authoring
  Rego, explaining it, and drafting PR notes. These are transformations of text
  the caller already has; giving them tools and a loop would add failure modes
  without adding capability.
* :meth:`AgentLLMClient.run_tool_loop` — the agent proper. Used for Q&A, where
  the model does need to go and look at the policies before it can answer.

Every tool the loop can reach is read-only, and the loop is bounded by an
iteration count and a wall clock. The agent has no route to the enforcement
chokepoint: it can describe what a policy would do and it cannot cause it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from app.providers.model_serving.client import (
    ChatMessage,
    ModelServingClient,
    ModelServingError,
)

logger = logging.getLogger(__name__)

ToolHandler = Callable[[Dict[str, Any]], Awaitable[Any]]


class AgentDisabled(RuntimeError):
    """The assistant is switched off in Settings."""


@dataclass
class Tool:
    """A function the model may call. Read-only, by construction."""

    name: str
    description: str
    parameters: Dict[str, Any]
    handler: ToolHandler

    def to_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolInvocation:
    """A call the model made, recorded so the UI can show its working."""

    tool: str
    arguments: Dict[str, Any]
    error: Optional[str] = None


@dataclass
class AgentResult:
    answer: str
    tool_calls: List[ToolInvocation] = field(default_factory=list)
    #: True when the loop hit its iteration or time limit before the model
    #: produced a final answer. The partial answer is still returned.
    truncated: bool = False


class AgentLLMClient:
    """Wraps :class:`ModelServingClient` with the agent's policies."""

    def __init__(self, client: Optional[ModelServingClient] = None):
        self._client = client or ModelServingClient()

    def _settings(self):
        from app.core.config import settings

        return settings

    def _require_enabled(self) -> None:
        settings = self._settings()
        if not settings.AGENT_ENABLED:
            raise AgentDisabled(
                "The policy assistant is disabled. Enable it in Settings."
            )
        if not self._client.configured:
            raise AgentDisabled(
                "No model is configured for the assistant. Set the AI Gateway model "
                "in Settings."
            )

    # --- One-shot ---------------------------------------------------------

    async def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
    ) -> str:
        """A single completion. No tools, no loop."""
        self._require_enabled()

        message = await self._client.chat(
            [
                ChatMessage(role="system", content=system),
                ChatMessage(role="user", content=user),
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return (message.get("content") or "").strip()

    # --- Tool loop --------------------------------------------------------

    async def run_tool_loop(
        self,
        system: str,
        user: str,
        tools: List[Tool],
        *,
        history: Optional[List[ChatMessage]] = None,
        max_iterations: Optional[int] = None,
    ) -> AgentResult:
        """Let the model call read-only tools until it can answer.

        Bounded twice over. ``AGENT_MAX_ITERATIONS`` caps the number of
        round trips, and ``AGENT_TIMEOUT_SECONDS`` caps the wall clock, because
        a model that calls the same tool repeatedly would otherwise satisfy the
        iteration cap slowly enough to tie up a worker.
        """
        self._require_enabled()
        settings = self._settings()

        limit = max_iterations or settings.AGENT_MAX_ITERATIONS
        deadline = time.monotonic() + settings.AGENT_TIMEOUT_SECONDS
        by_name = {tool.name: tool for tool in tools}
        schemas = [tool.to_schema() for tool in tools]

        messages: List[ChatMessage] = [ChatMessage(role="system", content=system)]
        if history:
            messages.extend(history)
        messages.append(ChatMessage(role="user", content=user))

        invocations: List[ToolInvocation] = []
        last_content = ""

        for iteration in range(limit):
            if time.monotonic() > deadline:
                logger.warning("Agent loop exceeded its time budget.")
                return AgentResult(
                    answer=last_content
                    or "I ran out of time before I could finish looking into that.",
                    tool_calls=invocations,
                    truncated=True,
                )

            try:
                message = await self._client.chat(messages, tools=schemas)
            except ModelServingError as e:
                logger.error("Agent chat call failed: %s", e)
                raise

            content = (message.get("content") or "").strip()
            if content:
                last_content = content

            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                return AgentResult(answer=content, tool_calls=invocations)

            messages.append(
                ChatMessage(
                    role="assistant",
                    content=content or None,
                    tool_calls=tool_calls,
                )
            )

            # Tools are independent and read-only, so running them concurrently
            # is safe and turns a multi-lookup turn into one round trip.
            results = await asyncio.gather(
                *(self._invoke(call, by_name, invocations) for call in tool_calls)
            )
            messages.extend(results)

            logger.debug(
                "Agent iteration %d/%d used %d tool(s).",
                iteration + 1,
                limit,
                len(tool_calls),
            )

        logger.warning("Agent loop hit its iteration limit of %d.", limit)
        return AgentResult(
            answer=last_content
            or "I wasn't able to reach an answer within the tool-call limit.",
            tool_calls=invocations,
            truncated=True,
        )

    async def _invoke(
        self,
        call: dict,
        by_name: Dict[str, Tool],
        invocations: List[ToolInvocation],
    ) -> ChatMessage:
        """Run one tool call and format its result as a tool message."""
        call_id = call.get("id") or ""
        function = call.get("function") or {}
        name = function.get("name") or ""

        raw_arguments = function.get("arguments")
        try:
            arguments = (
                json.loads(raw_arguments)
                if isinstance(raw_arguments, str) and raw_arguments.strip()
                else (raw_arguments or {})
            )
            if not isinstance(arguments, dict):
                arguments = {}
        except ValueError:
            arguments = {}
            logger.info("Model sent unparseable arguments for %s: %r", name, raw_arguments)

        record = ToolInvocation(tool=name, arguments=arguments)
        invocations.append(record)

        tool = by_name.get(name)
        if tool is None:
            record.error = "unknown tool"
            # Reported back to the model rather than raised. Being told the tool
            # does not exist lets it correct itself; an exception would end the
            # conversation over a recoverable mistake.
            return ChatMessage(
                role="tool",
                tool_call_id=call_id,
                name=name,
                content=f"No tool named {name!r} is available.",
            )

        try:
            result = await tool.handler(arguments)
            content = result if isinstance(result, str) else json.dumps(result, default=str)
        except Exception as e:
            logger.exception("Tool %s failed.", name)
            record.error = str(e)
            content = f"The tool failed: {e}"

        return ChatMessage(
            role="tool",
            tool_call_id=call_id,
            name=name,
            content=self._truncate(content),
        )

    def _truncate(self, content: str) -> str:
        """Cap a tool result so one large answer cannot blow the context window."""
        limit = self._settings().AGENT_MAX_TOOL_OUTPUT_CHARS
        if len(content) <= limit:
            return content
        return (
            content[:limit]
            + f"\n\n[truncated: {len(content) - limit} more characters. "
            "Narrow the query if you need the rest.]"
        )
