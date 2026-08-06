"""The conversation that can also propose an edit.

Two things are worth guarding here. One is the split between prose and a
proposed file, because getting it wrong in either direction is bad in a
different way: miss a real proposal and the user is told about a change they
cannot take; treat an illustrative snippet as a proposal and the diff appears to
delete every rule the snippet left out.

The other is that a proposal faces the same tier ceiling as the authoring path.
Reaching the model through a different endpoint must not be a way around it.
"""
from __future__ import annotations

import pytest

from app.agents import chat as agent_chat
from app.agents.guardrails import GuardrailViolation
from app.services.agent_llm import AgentResult, ToolInvocation


WHOLE_FILE = """package databricks.governance.clusters

rule_metadata := {
	"no_owner_tag": {
		"id": "CTL-CLU-001",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
}
"""


def fenced(body: str, language: str = "rego") -> str:
    return f"```{language}\n{body}```"


# --- Splitting prose from a proposal ----------------------------------------


def test_a_reply_with_no_code_is_all_prose():
    prose, rego = agent_chat.split_proposal("CST-CLU-005 fires on idle clusters.")

    assert prose == "CST-CLU-005 fires on idle clusters."
    assert rego is None


def test_a_trailing_file_is_lifted_out_of_the_prose():
    reply = f"I added a rule for the owner tag.\n\n{fenced(WHOLE_FILE)}"

    prose, rego = agent_chat.split_proposal(reply)

    assert prose == "I added a rule for the owner tag."
    assert rego is not None
    assert rego.startswith("package databricks.governance.clusters")
    assert "```" not in rego


def test_a_snippet_without_a_package_is_not_a_proposal():
    """The diff is against the whole open file, so a fragment treated as a
    replacement would read as deleting everything it omits."""
    reply = f"The condition is roughly:\n\n{fenced('count(tags) == 0\\n')}"

    prose, rego = agent_chat.split_proposal(reply)

    assert rego is None
    assert "count(tags)" in prose


def test_prose_after_the_block_is_kept():
    reply = f"Here it is.\n\n{fenced(WHOLE_FILE)}\n\nOpen a PR when you are happy."

    prose, rego = agent_chat.split_proposal(reply)

    assert rego is not None
    assert "Here it is." in prose
    assert "Open a PR when you are happy." in prose


def test_the_last_whole_file_wins():
    """Two files means the model changed its mind; the later one is where it
    landed."""
    first = WHOLE_FILE.replace("CTL-CLU-001", "CTL-CLU-999")
    reply = f"First try.\n\n{fenced(first)}\n\nActually, better:\n\n{fenced(WHOLE_FILE)}"

    _prose, rego = agent_chat.split_proposal(reply)

    assert "CTL-CLU-001" in rego
    assert "CTL-CLU-999" not in rego


def test_a_non_rego_fence_is_left_alone():
    """A JSON example is not a policy file."""
    reply = f'Findings look like this:\n\n{fenced("{}", language="json")}'

    _prose, rego = agent_chat.split_proposal(reply)

    assert rego is None


# --- The loop ---------------------------------------------------------------


class FakeLLM:
    """Stands in for the tool loop and the repair completion."""

    def __init__(self, reply: str, repairs: list[str] | None = None):
        self._reply = reply
        self._repairs = list(repairs or [])
        self.prompts: list[str] = []
        self.completions = 0

    async def run_tool_loop(self, system, user, tools, history=None, **kwargs):
        self.prompts.append(user)
        return AgentResult(
            answer=self._reply,
            tool_calls=[ToolInvocation(tool="read_policy", arguments={})],
        )

    async def complete(self, system, user, **kwargs):
        self.completions += 1
        return self._repairs.pop(0) if self._repairs else ""


@pytest.fixture
def compiles(monkeypatch):
    """`opa check` passes, without needing the binary."""

    async def ok(content, policy_name):
        return []

    monkeypatch.setattr("app.agents.author_rego.check_rego", ok)


@pytest.fixture(autouse=True)
def no_disk(monkeypatch):
    monkeypatch.setattr("app.agents.author_rego._is_new_file", lambda name: False)


async def test_a_question_gets_prose_and_no_proposal(compiles):
    llm = FakeLLM("CST-CLU-005 warns the owner after 30 idle days.")

    reply = await agent_chat.chat("What does CST-CLU-005 do?", llm=llm)

    assert reply.proposal is None
    assert reply.refusal is None
    assert "warns the owner" in reply.answer


async def test_an_edit_request_gets_both(compiles):
    llm = FakeLLM(f"Added the owner tag rule.\n\n{fenced(WHOLE_FILE)}")

    reply = await agent_chat.chat("Add an owner tag rule", target_policy="clusters.rego", llm=llm)

    assert reply.answer == "Added the owner tag rule."
    assert reply.proposal is not None
    assert reply.proposal.policy_name == "clusters.rego"
    assert reply.proposal.valid


async def test_the_open_file_is_given_to_the_model(compiles):
    llm = FakeLLM("Noted.")

    await agent_chat.chat(
        "Tighten this",
        target_policy="clusters.rego",
        open_content=WHOLE_FILE,
        llm=llm,
    )

    sent = llm.prompts[0]
    assert "clusters.rego" in sent
    assert "CTL-CLU-001" in sent


async def test_tool_calls_are_reported(compiles):
    llm = FakeLLM("Looked it up.")

    reply = await agent_chat.chat("What fired last night?", llm=llm)

    assert [call.tool for call in reply.tool_calls] == ["read_policy"]


# --- The ceiling still applies ----------------------------------------------


async def test_a_destructive_proposal_is_withdrawn_but_the_prose_survives(compiles):
    """Reaching the model through chat must not be a way around the ceiling.

    The prose is kept deliberately: it is where the user reads what the
    assistant was trying to do, and discarding it would leave them with a bare
    refusal and no context.
    """
    destructive = WHOLE_FILE.replace('"WARN"', '"DELETE"')
    llm = FakeLLM(f"This will delete them.\n\n{fenced(destructive)}")

    reply = await agent_chat.chat("Delete untagged clusters", llm=llm)

    assert reply.proposal is None
    assert reply.refusal is not None
    assert reply.refusal["error"] == "guardrail_violation"
    assert "This will delete them." in reply.answer


async def test_a_repair_faces_the_ceiling_too(monkeypatch):
    """The second draft is model output as well."""
    escalated = WHOLE_FILE.replace('"WARN"', '"TERMINATE"')
    llm = FakeLLM(
        f"Here you go.\n\n{fenced(WHOLE_FILE)}",
        repairs=[fenced(escalated)],
    )

    calls = {"n": 0}

    async def fails_once(content, policy_name):
        calls["n"] += 1
        return ["rego_parse_error: unexpected token"] if calls["n"] == 1 else []

    monkeypatch.setattr("app.agents.author_rego.check_rego", fails_once)

    reply = await agent_chat.chat("Add a rule", llm=llm)

    assert llm.completions == 1
    assert reply.proposal is None
    assert reply.refusal is not None


async def test_declaring_destructive_is_refused(compiles):
    llm = FakeLLM(fenced(WHOLE_FILE.replace('"destructive": false', '"destructive": true')))

    reply = await agent_chat.chat("Make it destructive", llm=llm)

    assert reply.proposal is None
    assert reply.refusal is not None


# --- Validation -------------------------------------------------------------


async def test_a_draft_that_does_not_compile_is_repaired_once(monkeypatch):
    llm = FakeLLM(f"Try this.\n\n{fenced(WHOLE_FILE)}", repairs=[fenced(WHOLE_FILE)])

    calls = {"n": 0}

    async def fails_once(content, policy_name):
        calls["n"] += 1
        return ["rego_parse_error: unexpected token"] if calls["n"] == 1 else []

    monkeypatch.setattr("app.agents.author_rego.check_rego", fails_once)

    reply = await agent_chat.chat("Add a rule", llm=llm)

    assert llm.completions == 1
    assert reply.proposal is not None
    assert reply.proposal.valid
    assert reply.proposal.attempts == 2


async def test_a_draft_that_stays_broken_is_returned_marked_invalid(monkeypatch):
    """Better to show the user a draft and the compiler error than nothing."""
    llm = FakeLLM(fenced(WHOLE_FILE), repairs=[fenced(WHOLE_FILE)])

    async def always_fails(content, policy_name):
        return ["rego_parse_error: still broken"]

    monkeypatch.setattr("app.agents.author_rego.check_rego", always_fails)

    reply = await agent_chat.chat("Add a rule", llm=llm)

    assert reply.proposal is not None
    assert not reply.proposal.valid
    assert reply.proposal.validation_errors == ["rego_parse_error: still broken"]


async def test_a_missing_opa_binary_does_not_trigger_a_repair(monkeypatch):
    """An unavailable binary is an environment problem. Asking the model to fix
    a compiler it cannot see wastes a call and a few seconds of the user's
    time."""
    llm = FakeLLM(fenced(WHOLE_FILE))

    async def no_binary(content, policy_name):
        return ["Could not run `opa check`: [Errno 2] No such file"]

    monkeypatch.setattr("app.agents.author_rego.check_rego", no_binary)

    reply = await agent_chat.chat("Add a rule", llm=llm)

    assert llm.completions == 0
    assert reply.proposal is not None
    assert not reply.proposal.valid
