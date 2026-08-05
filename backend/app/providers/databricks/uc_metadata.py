"""Batched Unity Catalog metadata reads.

Discovering tables one API call at a time does not scale: a mid-sized estate
has tens of thousands of them, and ``tables.get`` per table turns a scan into
an hour of round trips.

Instead this issues **one SQL statement per catalog** against
``information_schema``, which returns every table in that catalog with the
columns the policies actually care about. The cost goes from O(tables) HTTP
calls to O(catalogs).

Requires a SQL warehouse. When none is available the caller falls back to the
list APIs, which is slower but works.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Ordered by preference: a serverless warehouse spins up fastest for a metadata
# query that runs for a second or two.
_TABLE_QUERY = """
SELECT
    t.table_catalog,
    t.table_schema,
    t.table_name,
    t.table_owner,
    t.table_type,
    t.comment,
    t.created,
    t.last_altered
FROM {catalog}.information_schema.tables t
WHERE t.table_schema <> 'information_schema'
"""

_TAG_QUERY = """
SELECT
    catalog_name,
    schema_name,
    table_name,
    tag_name,
    tag_value
FROM {catalog}.information_schema.table_tags
"""


def pick_warehouse(workspace_client, preferred_id: Optional[str] = None) -> Optional[str]:
    """Choose a warehouse to run metadata queries on."""
    if preferred_id:
        return preferred_id

    try:
        warehouses = list(workspace_client.warehouses.list())
    except Exception as e:
        logger.warning("Could not list warehouses for UC metadata reads: %s", e)
        return None

    running = [w for w in warehouses if str(getattr(w.state, "value", w.state)) == "RUNNING"]
    for candidate in running + warehouses:
        if getattr(candidate, "id", None):
            return candidate.id
    return None


def _run_statement(workspace_client, warehouse_id: str, statement: str) -> List[Dict[str, Any]]:
    response = workspace_client.statement_execution.execute_statement(
        warehouse_id=warehouse_id,
        statement=statement,
        wait_timeout="50s",
    )

    status = getattr(response, "status", None)
    state = str(getattr(status, "state", "") or "")
    if "SUCCEEDED" not in state.upper():
        raise RuntimeError(f"Statement did not succeed (state={state}): {statement[:80]}")

    manifest = getattr(response, "manifest", None)
    schema = getattr(manifest, "schema", None)
    columns = [c.name for c in (getattr(schema, "columns", None) or [])]

    result = getattr(response, "result", None)
    rows = getattr(result, "data_array", None) or []
    return [dict(zip(columns, row)) for row in rows]


def fetch_uc_metadata(
    workspace_client,
    catalogs: List[str],
    *,
    warehouse_id: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """Return ``{full_table_name: metadata}`` for every table in ``catalogs``.

    One statement per catalog for tables, one more for tags. A catalog that
    fails is logged and skipped rather than sinking the whole read — partial
    metadata is more useful than none, and the caller marks affected tables so
    they aren't mistaken for compliant.
    """
    resolved_warehouse = pick_warehouse(workspace_client, warehouse_id)
    if not resolved_warehouse:
        logger.warning("No SQL warehouse available; skipping batched UC metadata read.")
        return {}

    metadata: Dict[str, Dict[str, Any]] = {}

    for catalog in catalogs:
        quoted = f"`{catalog}`"
        try:
            rows = _run_statement(
                workspace_client, resolved_warehouse, _TABLE_QUERY.format(catalog=quoted)
            )
        except Exception as e:
            logger.warning("Batched metadata read failed for catalog %s: %s", catalog, e)
            continue

        for row in rows:
            full_name = (
                f"{row.get('table_catalog')}.{row.get('table_schema')}.{row.get('table_name')}"
            )
            metadata[full_name] = {
                "catalog": row.get("table_catalog"),
                "schema": row.get("table_schema"),
                "name": row.get("table_name"),
                "owner": row.get("table_owner") or "unknown",
                "table_type": row.get("table_type"),
                "comment": row.get("comment"),
                "created": row.get("created"),
                "last_altered": row.get("last_altered"),
                "tags": {},
            }

        try:
            tag_rows = _run_statement(
                workspace_client, resolved_warehouse, _TAG_QUERY.format(catalog=quoted)
            )
        except Exception as e:
            # Tags are an enrichment; their absence shouldn't discard the tables.
            logger.debug("Could not read table tags for catalog %s: %s", catalog, e)
            continue

        for row in tag_rows:
            full_name = (
                f"{row.get('catalog_name')}.{row.get('schema_name')}.{row.get('table_name')}"
            )
            entry = metadata.get(full_name)
            if entry is not None and row.get("tag_name"):
                entry["tags"][row["tag_name"]] = row.get("tag_value") or ""

    logger.info(
        "Batched UC metadata read: %d tables across %d catalog(s).",
        len(metadata),
        len(catalogs),
    )
    return metadata
