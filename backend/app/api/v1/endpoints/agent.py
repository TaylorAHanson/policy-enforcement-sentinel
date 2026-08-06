"""The policy assistant's HTTP surface.

One endpoint per capability. None of them writes anything — not a resource, not
a file. Chat, authoring, and explanation all return text that a human puts
through the pull request flow in ``endpoints/policies.py``, which is the only
path by which a policy or its explanation reaches the repository.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agents import (
    author_rego,
    chat as agent_chat,
    explain_rego,
    pr_notes,
    qa,
    tools as agent_tools,
)
from app.agents.guardrails import MAX_GENERATED_TIER, GuardrailViolation
from app.core.config import settings
from app.services import explanation_cache
from app.services.agent_llm import AgentDisabled

logger = logging.getLogger(__name__)

router = APIRouter()


class AuthorRequest(BaseModel):
    instruction: str = Field(..., min_length=3)
    target_policy: Optional[str] = None
    existing_content: Optional[str] = None


class ExplainRequest(BaseModel):
    policy_name: str
    content: str


class PrNotesRequest(BaseModel):
    policy_name: str
    new_content: str
    old_content: str = ""


class AskRequest(BaseModel):
    question: str = Field(..., min_length=2)
    history: List[Dict[str, Any]] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=2)
    history: List[Dict[str, Any]] = Field(default_factory=list)
    #: What the user has open. Context for the reply, not an instruction to
    #: rewrite it — a question about an open policy still gets an answer.
    target_policy: Optional[str] = None
    open_content: Optional[str] = None


def _handle_disabled(e: AgentDisabled) -> HTTPException:
    # 503 rather than 403: the capability exists and is switched off, which is a
    # different thing from the caller not being allowed to use it, and the UI
    # renders the two differently.
    return HTTPException(status_code=503, detail=str(e))


@router.get("/status")
async def agent_status():
    """Whether the assistant is usable, and what it can reach."""
    from app.providers.model_serving.client import ModelServingClient

    client = ModelServingClient()
    return {
        "enabled": settings.AGENT_ENABLED,
        "configured": client.configured,
        "model": client.gateway_model or client.endpoint_name,
        "via_gateway": bool(client.gateway_model),
        "reasoning_effort": settings.AGENT_LLM_REASONING_EFFORT,
        "max_iterations": settings.AGENT_MAX_ITERATIONS,
        "tools": agent_tools.tool_names(),
        "max_generated_tier": int(MAX_GENERATED_TIER),
        "tracing_enabled": settings.MLFLOW_TRACING_ENABLED,
    }


@router.post("/author")
async def author(payload: AuthorRequest):
    """Draft a policy. Returns a proposal; nothing is written."""
    try:
        result = await author_rego.author_rego(
            payload.instruction,
            target_policy=payload.target_policy,
            existing_content=payload.existing_content,
        )
    except AgentDisabled as e:
        raise _handle_disabled(e)
    except GuardrailViolation as e:
        logger.warning("Rejected generated policy: %s", e)
        # 422 rather than 500: the request was understood and the result was
        # refused on policy grounds, which the UI needs to explain rather than
        # report as a failure.
        raise HTTPException(status_code=422, detail=e.to_dict())
    except Exception as e:
        logger.exception("Authoring failed.")
        raise HTTPException(status_code=502, detail=str(e))

    return result.to_dict()


@router.post("/explain")
async def explain(payload: ExplainRequest):
    """Plain-English explanation of a policy.

    Cached on a hash of the content, because the editor now asks for this
    whenever the tab is open and the policy has changed rather than when someone
    presses a button — so the same draft would otherwise be explained once per
    tab switch, per reload, and per reader.
    """
    sha = explain_rego.content_sha(payload.content)

    cached = explanation_cache.get(sha)
    if cached is not None:
        return {
            "policy_name": payload.policy_name,
            "explanation": cached,
            "cached": True,
        }

    try:
        text = await explain_rego.explain_rego(payload.policy_name, payload.content)
    except AgentDisabled as e:
        raise _handle_disabled(e)
    except Exception as e:
        logger.exception("Explanation failed.")
        raise HTTPException(status_code=502, detail=str(e))

    explanation_cache.put(sha, payload.policy_name, text)

    # Cached, but never written to the policies directory. An explanation
    # reaches the repository only by being committed alongside its policy in a
    # pull request; the working copy is rebuilt on the next restart.
    return {"policy_name": payload.policy_name, "explanation": text, "cached": False}


@router.get("/explain/{policy_name}")
async def get_committed_explanation(policy_name: str):
    """The committed sibling ``.md``, if there is one.

    Cheap and offline — the editor calls this on every policy selection, and
    only falls back to generating when it comes back empty.
    """
    text = explain_rego.read_explanation(policy_name)
    return {
        "policy_name": policy_name,
        "explanation": text,
        "exists": text is not None,
    }


@router.post("/pr-notes")
async def notes(payload: PrNotesRequest):
    """A PR body for a policy change, with the blast radius filled in."""
    try:
        return await pr_notes.pr_notes(
            payload.policy_name,
            payload.new_content,
            old_content=payload.old_content,
        )
    except AgentDisabled as e:
        raise _handle_disabled(e)
    except Exception as e:
        logger.exception("PR note generation failed.")
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/chat")
async def chat(payload: ChatRequest):
    """Answer, and propose an edit when one was asked for.

    A guardrail violation does not fail the request the way ``/author`` does.
    The proposal is dropped and reported in ``refusal``, but the prose survives:
    the model's account of what it was trying to do is usually where the user
    finds out why it was refused, and throwing a 422 would discard it.
    """
    try:
        reply = await agent_chat.chat(
            payload.message,
            history=payload.history,
            target_policy=payload.target_policy,
            open_content=payload.open_content,
        )
    except AgentDisabled as e:
        raise _handle_disabled(e)
    except Exception as e:
        logger.exception("The assistant could not reply.")
        raise HTTPException(status_code=502, detail=str(e))

    return reply.to_dict()


@router.post("/ask")
async def ask(payload: AskRequest):
    """Answer a question using the read-only tools."""
    try:
        result = await qa.answer_question(payload.question, history=payload.history)
    except AgentDisabled as e:
        raise _handle_disabled(e)
    except Exception as e:
        logger.exception("The assistant could not answer.")
        raise HTTPException(status_code=502, detail=str(e))

    return {
        "answer": result.answer,
        "truncated": result.truncated,
        "tool_calls": [
            {"tool": call.tool, "arguments": call.arguments, "error": call.error}
            for call in result.tool_calls
        ],
    }
