"""Idempotent startup migrations.

There is no Alembic here, and deliberately so: this app creates its tables with
``Base.metadata.create_all`` on every boot, which handles new tables but not new
columns on existing ones. This module fills that gap.

Every migration must be safe to run repeatedly and against a fresh database
where the change is already present — they run on every startup, in production,
before the app serves traffic. Check first, then act; never assume.

They must also be non-destructive. Adding a column, adding an index, and
backfilling a null are in scope. Dropping or retyping a column is not: do that
by hand, with a backup, at a time you have chosen.
"""
from __future__ import annotations

import logging
from typing import Callable, List, Tuple

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def _dialect(engine: Engine) -> str:
    return engine.dialect.name


def _table_exists(engine: Engine, table: str) -> bool:
    return inspect(engine).has_table(table)


def _columns(engine: Engine, table: str) -> set:
    if not _table_exists(engine, table):
        return set()
    return {col["name"] for col in inspect(engine).get_columns(table)}


def _indexes(engine: Engine, table: str) -> set:
    if not _table_exists(engine, table):
        return set()
    return {idx["name"] for idx in inspect(engine).get_indexes(table)}


def add_column(engine: Engine, table: str, column: str, ddl_type: str, default=None) -> bool:
    """Add a column if it isn't already there. Returns whether it did anything."""
    if not _table_exists(engine, table):
        return False
    if column in _columns(engine, table):
        return False

    clause = f'ALTER TABLE {table} ADD COLUMN {column} {ddl_type}'
    if default is not None:
        clause += f" DEFAULT {default}"

    with engine.begin() as conn:
        conn.execute(text(clause))
    logger.info("Migration: added %s.%s", table, column)
    return True


def add_index(engine: Engine, table: str, name: str, columns: List[str]) -> bool:
    if not _table_exists(engine, table):
        return False
    if name in _indexes(engine, table):
        return False

    column_list = ", ".join(columns)
    with engine.begin() as conn:
        conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({column_list})"))
    logger.info("Migration: added index %s on %s(%s)", name, table, column_list)
    return True


def backfill(engine: Engine, statement: str, description: str) -> bool:
    with engine.begin() as conn:
        result = conn.execute(text(statement))
    affected = getattr(result, "rowcount", 0) or 0
    if affected:
        logger.info("Migration: %s (%d row(s))", description, affected)
    return bool(affected)


# --- The migrations ---------------------------------------------------------


def _m_run_counters(engine: Engine) -> None:
    """Denormalised counters on sentinel_runs, added when results shrank to a summary."""
    for column in (
        "total_resources",
        "violation_count",
        "check_count",
        "remediated_count",
        "downgraded_count",
    ):
        add_column(engine, "sentinel_runs", column, "INTEGER", default=0)

    add_column(engine, "sentinel_runs", "approved_by", "VARCHAR")
    add_column(engine, "sentinel_runs", "approval_id", "VARCHAR")

    backfill(
        engine,
        "UPDATE sentinel_runs SET total_resources = 0 WHERE total_resources IS NULL",
        "defaulted null run counters",
    )


def _m_finding_safety_columns(engine: Engine) -> None:
    """The action columns, added with the safety model.

    Findings written before the ladder existed carry a bare ``action``. Copying
    it into both ``requested_action`` and ``effective_action`` is the honest
    reading: at the time, there was no gap between the two.
    """
    add_column(engine, "sentinel_findings", "requested_action", "VARCHAR")
    add_column(engine, "sentinel_findings", "effective_action", "VARCHAR")
    add_column(engine, "sentinel_findings", "tier", "INTEGER")
    add_column(engine, "sentinel_findings", "requested_tier", "INTEGER")
    add_column(engine, "sentinel_findings", "downgrade_reason", "TEXT")
    add_column(engine, "sentinel_findings", "executed", "BOOLEAN", default=0)
    add_column(engine, "sentinel_findings", "policy_id", "VARCHAR")
    add_column(engine, "sentinel_findings", "category", "VARCHAR")
    add_column(engine, "sentinel_findings", "rule_id", "VARCHAR")

    if "action" in _columns(engine, "sentinel_findings"):
        backfill(
            engine,
            "UPDATE sentinel_findings SET requested_action = action "
            "WHERE requested_action IS NULL AND action IS NOT NULL",
            "backfilled requested_action from the legacy action column",
        )
        backfill(
            engine,
            "UPDATE sentinel_findings SET effective_action = action "
            "WHERE effective_action IS NULL AND action IS NOT NULL",
            "backfilled effective_action from the legacy action column",
        )

    # Historical KILL/BLOCK values map onto the ladder so old findings render
    # with a tier instead of an unrecognised action.
    backfill(
        engine,
        "UPDATE sentinel_findings SET effective_action = 'TERMINATE' WHERE effective_action = 'KILL'",
        "renamed legacy KILL findings to TERMINATE",
    )
    backfill(
        engine,
        "UPDATE sentinel_findings SET effective_action = 'REVOKE_ACCESS' WHERE effective_action = 'BLOCK'",
        "renamed legacy BLOCK findings to REVOKE_ACCESS",
    )


def _m_finding_indexes(engine: Engine) -> None:
    add_index(engine, "sentinel_findings", "ix_findings_run_kind", ["run_id", "kind"])
    add_index(
        engine,
        "sentinel_findings",
        "ix_findings_run_kind_severity",
        ["run_id", "kind", "severity"],
    )
    add_index(
        engine, "sentinel_findings", "ix_findings_run_action", ["run_id", "effective_action"]
    )


def _m_audit_columns(engine: Engine) -> None:
    add_column(engine, "enforcement_audit", "undo_payload", "JSON")
    add_column(engine, "enforcement_audit", "undone_at", "TIMESTAMP")
    add_column(engine, "enforcement_audit", "undone_by", "VARCHAR")
    add_column(engine, "enforcement_audit", "approved_by", "VARCHAR")
    add_column(engine, "enforcement_audit", "approval_id", "VARCHAR")
    add_column(engine, "enforcement_audit", "downgrade_reason", "TEXT")
    add_column(engine, "enforcement_audit", "requested_action", "VARCHAR")
    add_column(engine, "enforcement_audit", "tier", "INTEGER", default=0)


def _m_allowlist_expiry(engine: Engine) -> None:
    """Exceptions gained an expiry date. Existing rows keep null (never expires)."""
    add_column(engine, "allowlist", "expires_at", "TIMESTAMP")


MIGRATIONS: List[Tuple[str, Callable[[Engine], None]]] = [
    ("allowlist_expiry", _m_allowlist_expiry),
    ("run_counters", _m_run_counters),
    ("finding_safety_columns", _m_finding_safety_columns),
    ("finding_indexes", _m_finding_indexes),
    ("audit_columns", _m_audit_columns),
]


def run_startup_migrations(engine: Engine = None) -> None:
    """Run every migration. Safe to call on every boot.

    A failure is logged and the rest continue: one migration that can't apply
    (a permissions problem, say) shouldn't stop the app from starting, and the
    ones after it are independent.
    """
    if engine is None:
        from app.db.session import get_engine

        engine = get_engine()

    logger.debug("Running startup migrations (dialect: %s).", _dialect(engine))

    for name, migration in MIGRATIONS:
        try:
            migration(engine)
        except Exception as e:
            logger.error("Migration %s failed: %s: %s", name, type(e).__name__, e)
