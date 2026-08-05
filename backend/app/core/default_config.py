"""In-code defaults — the lowest layer of the configuration stack.

Config resolves in three layers, each overriding the one before:

    default_config.py  ->  env / .env / databricks.yml  ->  DB (Admin Settings)

Anything a Platform Admin should be able to change at runtime belongs here and
in ``settings_store.EDITABLE_FIELDS``, not hardcoded at its point of use.
"""
from typing import Any, Dict

# Branding. Never hardcode these strings anywhere else.
BRANDING: Dict[str, Any] = {
    "BRANDING_NAME": "Policy Enforcement Sentinel",
    "BRANDING_LOGO_URL": "https://www.openpolicyagent.org/img/nav/logo.png",
    "BRANDING_PRIMARY_COLOR": "#4299e0",
    "BRANDING_SECONDARY_COLOR": "#0b0f15",
}

# Safety defaults. Every one of these is deliberately the least capable value.
# A fresh install warns and does nothing else until an admin makes a decision.
SAFETY: Dict[str, Any] = {
    "ENFORCEMENT_ENABLED": False,
    "DESTRUCTIVE_ACTION_WORKSPACES": "",
    "DESTRUCTIVE_ACTION_MAX_RESOURCES": 5,
    "ENFORCEMENT_APPROVAL_TTL_MINUTES": 30,
    "SENTINEL_CRON_MODE": "audit",
}

# Scan tuning. Concurrency is bounded rather than unlimited so a large estate
# does not exhaust the SDK's connection pool or the workspace's rate limits.
SCAN: Dict[str, Any] = {
    "SENTINEL_SCAN_CONCURRENCY": 5,
    "SENTINEL_WORKSPACE_CONCURRENCY": 2,
    "SENTINEL_WORKSPACE_SCAN_TIMEOUT_SECONDS": 900,
    "SENTINEL_SDK_HTTP_TIMEOUT_SECONDS": 60,
    "SENTINEL_SCAN_NOTEBOOKS": False,
}

# The policy assistant. Routed through the AI Gateway so rate limits, cost
# controls, and guardrails are gateway configuration rather than code.
#
# `AGENT_LLM_REASONING_EFFORT` defaults to "none" because gpt-5.6 luna rejects a
# request that combines function tools with any other value, and the Q&A loop is
# built on function tools. A blank value omits the parameter altogether, which is
# what a non-reasoning model needs.
AGENT: Dict[str, Any] = {
    "AGENT_ENABLED": True,
    "AI_GATEWAY_ENDPOINT": "system.ai.gpt-5-6-luna",
    "MODEL_SERVING_AGENT_LLM_ENDPOINT": "",
    "AGENT_LLM_REASONING_EFFORT": "none",
    "AGENT_MAX_ITERATIONS": 5,
    "AGENT_TIMEOUT_SECONDS": 120,
    "AGENT_MAX_TOOL_OUTPUT_CHARS": 25000,
    "MODEL_SERVING_TIMEOUT_SECONDS": 120.0,
}

# Where run summaries and enforcement alerts are sent.
NOTIFICATIONS: Dict[str, Any] = {
    "SMTP_SERVER": "localhost",
    "SMTP_PORT": 1025,
    "SMTP_FROM_EMAIL": "admin@your-company.com",
    "SMTP_ADMIN_EMAIL": "admin@your-company.com",
}

DEFAULTS: Dict[str, Any] = {
    **BRANDING,
    **SAFETY,
    **SCAN,
    **AGENT,
    **NOTIFICATIONS,
}
