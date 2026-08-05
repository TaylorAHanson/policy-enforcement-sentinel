"""The policy assistant.

Four capabilities, three of them one-shot transformations of text the caller
already has, and one — Q&A — a bounded tool loop.

The safety boundary is structural rather than prompted. The authoring
capability's output is checked for tier and destructiveness after generation, by
:mod:`app.agents.guardrails`, which does not consult the prompt and does not
trust the model. The Q&A loop's tools are built from a fixed list in
:mod:`app.agents.tools`; none of them import a handler or the destructive
wrapper, so there is no tool through which the assistant can act on a resource.

Import the submodules rather than re-exporting their entry points here: each
capability's main function shares its module's name, so a re-export would shadow
the module and turn ``agents.pr_notes.pr_notes(...)`` into an AttributeError.
"""
from app.agents import (  # noqa: F401
    author_rego,
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
    "explain_rego",
    "guardrails",
    "pr_notes",
    "prompts",
    "qa",
    "tools",
    "tracing",
]
