"""The policy assistant.

Five capabilities: three one-shot transformations of text the caller already
has, and two bounded tool loops — :mod:`app.agents.chat`, which the editor uses,
and :mod:`app.agents.qa`, which answers without being able to propose an edit.

The safety boundary is structural rather than prompted. Anything the model
writes is checked for tier and destructiveness after generation by
:mod:`app.agents.guardrails`, which does not consult the prompt and does not
trust the model. The tool loops' tools are built from a fixed list in
:mod:`app.agents.tools`; none of them import a handler or the destructive
wrapper, so there is no tool through which the assistant can act on a resource.

Import the submodules rather than re-exporting their entry points here: each
capability's main function shares its module's name, so a re-export would shadow
the module and turn ``agents.pr_notes.pr_notes(...)`` into an AttributeError.
"""
from app.agents import (  # noqa: F401
    author_rego,
    chat,
    explain_rego,
    guardrails,
    pr_notes,
    prompts,
    qa,
    tools,
    tracing,
)

__all__ = [
    "author_rego",
    "chat",
    "explain_rego",
    "guardrails",
    "pr_notes",
    "prompts",
    "qa",
    "tools",
    "tracing",
]
