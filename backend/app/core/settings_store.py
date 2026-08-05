"""Runtime, admin-editable configuration overrides.

Layer three of three. A curated subset of settings is backed by the
``app_settings`` table so a Platform Admin can change them in the UI without a
code edit or redeploy.

Two rules keep this honest:

* **Only fields listed in :data:`EDITABLE_FIELDS` are editable.** Secrets,
  connection strings, and anything that needs a restart to take effect are
  deliberately absent — a settings page that appears to change something it
  cannot is worse than not offering it.
* **Overrides are applied by mutating the live ``settings`` object**, so
  consumers that read ``settings.X`` at call time see the change immediately.
  This is why the golden rule about not caching settings at import exists.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings

logger = logging.getLogger(__name__)


#: The schema the Settings page renders. ``type`` drives both the input widget
#: and the coercion applied on load: bool | int | string | color | textarea.
#:
#: ``danger`` marks the group that can cause irreversible action. The UI renders
#: it separately and more loudly; see src/pages/Settings.tsx.
EDITABLE_FIELDS: List[Dict[str, Any]] = [
    # --- Enforcement safety -------------------------------------------------
    {
        "group": "Enforcement safety",
        "danger": True,
        "key": "ENFORCEMENT_ENABLED",
        "label": "Enable enforcement",
        "type": "bool",
        "help": (
            "Master switch for destructive actions. While this is off, every Tier 3 "
            "action is downgraded no matter what a policy asks for. Turning it on "
            "does not by itself allow anything — the other four gates still apply."
        ),
    },
    {
        "group": "Enforcement safety",
        "danger": True,
        "key": "DESTRUCTIVE_ACTION_WORKSPACES",
        "label": "Workspaces where destructive actions are permitted",
        "type": "string",
        "help": (
            "Comma-separated workspace names. Empty means nowhere, which is the "
            "default. A workspace absent from this list can never be acted on "
            "destructively, regardless of policy or mode."
        ),
    },
    {
        "group": "Enforcement safety",
        "danger": True,
        "key": "DESTRUCTIVE_ACTION_MAX_RESOURCES",
        "label": "Blast radius limit",
        "type": "int",
        "min": 0,
        "max": 1000,
        "help": (
            "If a single run would destructively act on more resources than this, "
            "every Tier 3 action in the run is refused and downgraded. This is the "
            "guard against a policy edit that unexpectedly matches everything."
        ),
    },
    {
        "group": "Enforcement safety",
        "danger": True,
        "key": "ENFORCEMENT_APPROVAL_TTL_MINUTES",
        "label": "Approval validity (minutes)",
        "type": "int",
        "min": 1,
        "max": 1440,
        "help": (
            "How long an operator's confirmation of a run stays valid. Approvals are "
            "scoped to a single run and expire so a stale confirmation can't authorise "
            "a later scan."
        ),
    },
    # --- Scanning -----------------------------------------------------------
    {
        "group": "Scanning",
        "key": "SENTINEL_CRON_SCHEDULE",
        "label": "Scan schedule",
        "type": "cron",
        "help": (
            "Five-field cron expression in UTC, e.g. '0 2 * * *' for 02:00 daily. "
            "Leave blank to disable scheduled scanning entirely. Takes effect "
            "within a minute; no restart needed."
        ),
    },
    {
        "group": "Scanning",
        "key": "SENTINEL_CRON_WORKSPACE",
        "label": "Scheduled scan workspace",
        "type": "string",
        "help": "Which workspace the scheduled scan covers.",
    },
    {
        "group": "Scanning",
        "key": "SENTINEL_CRON_ENV",
        "label": "Scheduled scan environment",
        "type": "string",
        "help": "The environment label passed to policies for the scheduled scan, e.g. prod.",
    },
    {
        "group": "Scanning",
        "key": "SENTINEL_CRON_MODE",
        "label": "Scheduled scan mode",
        "type": "select",
        "options": ["audit", "remediate", "enforce"],
        # Dangerous because it applies to unattended runs. Every other route to
        # a destructive action has a human watching it; this one is a decision
        # made once that then acts on a schedule, with nobody in the room.
        "danger": True,
        "help": (
            "audit records findings and changes nothing. remediate permits reversible "
            "actions. enforce additionally permits destructive ones, subject to every gate."
        ),
    },
    {
        "group": "Scanning",
        "key": "SENTINEL_SCAN_CONCURRENCY",
        "label": "Scan concurrency (within a workspace)",
        "type": "int",
        "min": 1,
        "max": 50,
        "help": "Concurrent discovery and evaluation units inside one workspace scan.",
    },
    {
        "group": "Scanning",
        "key": "SENTINEL_WORKSPACE_CONCURRENCY",
        "label": "Workspace concurrency",
        "type": "int",
        "min": 1,
        "max": 20,
        "help": "How many workspaces are scanned at once.",
    },
    {
        "group": "Scanning",
        "key": "SENTINEL_WORKSPACE_SCAN_TIMEOUT_SECONDS",
        "label": "Per-workspace scan timeout (seconds)",
        "type": "int",
        "min": 30,
        "max": 7200,
        "help": "Wall-clock cap on one workspace's scan. Exceeding it records a failure rather than hanging the run.",
    },
    {
        "group": "Scanning",
        "key": "SENTINEL_SDK_HTTP_TIMEOUT_SECONDS",
        "label": "Databricks SDK HTTP timeout (seconds)",
        "type": "int",
        "min": 5,
        "max": 600,
    },
    {
        "group": "Scanning",
        "key": "SENTINEL_SCAN_NOTEBOOKS",
        "label": "Scan notebooks",
        "type": "bool",
        "help": "Walking the whole workspace tree is slow. Off by default.",
    },
    # --- Agent --------------------------------------------------------------
    {
        "group": "Agent",
        "key": "AGENT_ENABLED",
        "label": "Enable the policy assistant",
        "type": "bool",
        "help": "Powers Rego authoring, plain-English explanations, PR notes, and Q&A.",
    },
    {
        "group": "Agent",
        "key": "AI_GATEWAY_ENDPOINT",
        "label": "AI Gateway model",
        "type": "string",
        "help": (
            "Model served through the AI Gateway, e.g. system.ai.gpt-5-6-luna. Rate "
            "limits, cost controls, and guardrails are configured on the gateway."
        ),
    },
    {
        "group": "Agent",
        "key": "MODEL_SERVING_AGENT_LLM_ENDPOINT",
        "label": "Fallback serving endpoint",
        "type": "string",
        "help": "Used when no gateway model is configured.",
    },
    {
        "group": "Agent",
        "key": "AGENT_LLM_REASONING_EFFORT",
        "label": "Reasoning effort",
        "type": "select",
        "options": ["none", "low", "medium", "high", ""],
        "help": (
            "Must be 'none' for gpt-5.6 luna, which rejects function tools combined "
            "with any other value. Blank omits the parameter entirely."
        ),
    },
    {
        "group": "Agent",
        "key": "AGENT_MAX_ITERATIONS",
        "label": "Max tool-loop iterations",
        "type": "int",
        "min": 1,
        "max": 20,
    },
    # --- Notifications ------------------------------------------------------
    {
        "group": "Notifications",
        "key": "SMTP_FROM_EMAIL",
        "label": "From address",
        "type": "string",
    },
    {
        "group": "Notifications",
        "key": "SMTP_ADMIN_EMAIL",
        "label": "Admin recipients",
        "type": "string",
        "help": "Comma-separate multiple addresses. Receives run summaries and enforcement alerts.",
    },
    # --- Branding -----------------------------------------------------------
    {
        "group": "Branding",
        "key": "BRANDING_NAME",
        "label": "Application name",
        "type": "string",
    },
    {"group": "Branding", "key": "BRANDING_LOGO_URL", "label": "Logo URL", "type": "string"},
    {
        "group": "Branding",
        "key": "BRANDING_PRIMARY_COLOR",
        "label": "Primary colour",
        "type": "color",
    },
    {
        "group": "Branding",
        "key": "BRANDING_SECONDARY_COLOR",
        "label": "Secondary colour",
        "type": "color",
    },
]

FIELDS_BY_KEY: Dict[str, Dict[str, Any]] = {field["key"]: field for field in EDITABLE_FIELDS}

#: Changing one of these has safety consequences, so writes are logged loudly
#: and the UI requires an extra confirmation.
DANGER_KEYS = {field["key"] for field in EDITABLE_FIELDS if field.get("danger")}


def validate_cron(expression: str) -> Optional[str]:
    """Why ``expression`` is not a usable cron, or None when it is fine.

    Blank is valid and means "no schedule". Anything else has to parse, because
    an unparseable expression leaves the scheduler idle — visible only as one
    line in a log, while the Settings page goes on displaying the value as
    though it were in force.
    """
    text = expression.strip()
    if not text:
        return None

    # Checked before handing it over, because the wrong number of fields is the
    # mistake people actually make and croniter reports it as "Exactly 5, 6 or 7
    # columns has to be specified for iterator expression", which explains the
    # library rather than the typo.
    count = len(text.split())
    if count not in (5, 6, 7):
        return (
            f"Expected 5 fields (minute hour day-of-month month day-of-week), "
            f"got {count}."
        )

    from croniter import croniter

    try:
        croniter(text, datetime.now(timezone.utc))
    except Exception as e:
        return str(e)
    return None


def next_cron_runs(expression: str, count: int = 3) -> List[str]:
    """The next few fire times, ISO-formatted in UTC. Empty when unusable."""
    if validate_cron(expression) is not None or not expression.strip():
        return []

    from croniter import croniter

    cron = croniter(expression.strip(), datetime.now(timezone.utc))
    return [cron.get_next(datetime).isoformat() for _ in range(count)]


def _coerce(field: Dict[str, Any], raw: Optional[str]) -> Any:
    """Turn the stored string back into the type the setting expects."""
    if raw is None:
        return None

    field_type = field.get("type", "string")
    if field_type == "cron":
        text = str(raw).strip()
        if validate_cron(text) is not None:
            logger.warning(
                "Setting %s has an unparseable cron override %r; ignoring.",
                field["key"],
                raw,
            )
            return None
        # Blank is a real value here — it disables the schedule — so it must
        # survive rather than be treated as "no override".
        return text
    if field_type == "bool":
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    if field_type == "int":
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            logger.warning("Setting %s has non-integer override %r; ignoring.", field["key"], raw)
            return None
        if "min" in field:
            value = max(field["min"], value)
        if "max" in field:
            value = min(field["max"], value)
        return value
    if field_type == "select":
        options = field.get("options") or []
        if options and raw not in options:
            logger.warning(
                "Setting %s has override %r outside its allowed values; ignoring.",
                field["key"],
                raw,
            )
            return None
    return raw


def _serialize(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def get_overrides(db: Session) -> Dict[str, Any]:
    """Read every stored override, coerced and filtered to known fields."""
    from app.db.app_setting import AppSettingModel

    overrides: Dict[str, Any] = {}
    for row in db.query(AppSettingModel).all():
        field = FIELDS_BY_KEY.get(row.key)
        if field is None:
            # A row for a setting that no longer exists. Inert by design.
            continue
        value = _coerce(field, row.value)
        if value is not None:
            overrides[row.key] = value
    return overrides


def load_overrides(db: Session) -> Dict[str, Any]:
    """Apply stored overrides onto the live settings object. Called at startup."""
    overrides = get_overrides(db)
    for key, value in overrides.items():
        _apply(key, value)

    if overrides:
        logger.info("Applied %d setting override(s) from the database.", len(overrides))

    # Whatever else happened, say plainly whether enforcement is live. This is
    # the line to look for in backend.log when something was unexpectedly acted on.
    if getattr(settings, "ENFORCEMENT_ENABLED", False):
        logger.warning(
            "ENFORCEMENT IS ENABLED. Destructive actions are possible in: %s",
            settings.DESTRUCTIVE_ACTION_WORKSPACES or "(no workspaces allowlisted)",
        )
    else:
        logger.info("Enforcement is disabled; destructive actions will be downgraded.")

    return overrides


def _apply(key: str, value: Any) -> None:
    """Mutate the live settings object so call-time readers see the change."""
    if not hasattr(settings, key):
        logger.warning("Ignoring override for unknown setting %s.", key)
        return
    setattr(settings, key, value)


def set_override(db: Session, key: str, value: Any, updated_by: Optional[str] = None) -> Any:
    """Persist one override and apply it immediately."""
    from app.db.app_setting import AppSettingModel

    field = FIELDS_BY_KEY.get(key)
    if field is None:
        raise ValueError(f"{key} is not an editable setting")

    serialized = _serialize(value)

    # Rejected at the point of entry rather than stored and ignored. A cron
    # typo that is merely logged leaves the page showing a schedule that will
    # never fire.
    if field.get("type") == "cron":
        problem = validate_cron(serialized)
        if problem is not None:
            raise ValueError(f"{serialized!r} is not a valid cron expression: {problem}")

    coerced = _coerce(field, serialized)
    if coerced is None and field.get("type") in ("int", "select", "cron"):
        raise ValueError(f"{value!r} is not a valid value for {key}")

    row = db.query(AppSettingModel).filter(AppSettingModel.key == key).one_or_none()
    if row is None:
        row = AppSettingModel(key=key, value=serialized, updated_by=updated_by)
        db.add(row)
    else:
        row.value = serialized
        row.updated_by = updated_by

    _apply(key, coerced)

    if key in DANGER_KEYS:
        logger.warning(
            "SAFETY SETTING CHANGED: %s set to %r by %s",
            key,
            coerced,
            updated_by or "unknown",
        )
    else:
        logger.info("Setting %s updated by %s.", key, updated_by or "unknown")

    return coerced


def clear_override(db: Session, key: str) -> None:
    """Drop an override, falling back to the env/in-code default."""
    from app.db.app_setting import AppSettingModel

    db.query(AppSettingModel).filter(AppSettingModel.key == key).delete()

    # Re-derive the pre-override value from the env layer.
    from app.core.config import Settings

    fresh = Settings()
    if hasattr(fresh, key):
        _apply(key, getattr(fresh, key))


def describe(db: Session) -> List[Dict[str, Any]]:
    """The schema plus current values, as rendered by the Settings page."""
    overrides = get_overrides(db)
    described = []
    for field in EDITABLE_FIELDS:
        key = field["key"]
        described.append(
            {
                **field,
                "value": getattr(settings, key, None),
                "overridden": key in overrides,
            }
        )
    return described
