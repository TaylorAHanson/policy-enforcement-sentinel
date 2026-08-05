# Backend AGENTS.md

FastAPI backend for the Enforcement Sentinel. Read the root `AGENTS.md` first —
its golden rule about non-destructive defaults applies most directly to this
directory.

## Layout

| Path | What |
|---|---|
| `app/core/actions.py` | **The action ladder.** Tiers 0-3, reversibility, handler verbs. Single source of truth. |
| `app/core/enforcement.py` | **The chokepoint.** `resolve_effective_action()` and the five destructive gates. |
| `app/core/config.py` | Pydantic settings (env layer). |
| `app/core/default_config.py` | In-code defaults, lowest config layer. |
| `app/core/settings_store.py` | DB-backed setting overrides + the editable-field schema the UI renders. |
| `app/services/sentinel_service.py` | The scan engine: discovery, evaluation, remediation. |
| `app/services/policy_registry.py` | Parses Rego metadata and validates policy safety. |
| `app/services/policy_sync.py` | Rebuilds the policy working copy from the target branch. |
| `app/providers/opa/` | OPA client + embedded server manager. |
| `app/providers/databricks/handlers/` | One handler per resource type. |
| `app/providers/databricks/destructive.py` | **The only place destructive SDK calls may live.** |
| `app/agents/` | AI Gateway capabilities: author, explain, PR notes, Q&A. |
| `app/db/` | SQLAlchemy models, session, startup migrations. |

## The enforcement path

Everything that acts on a resource follows the same route:

```
policy requested_action
  -> resolve_effective_action(request)   # app/core/enforcement.py
  -> EffectiveAction(action, tier, downgrade_reason)
  -> handler protocol method             # SupportsTerminate / SupportsRevokeAccess / ...
  -> destructive.py (Tier 3 only)
  -> enforcement_audit row (intent written BEFORE execution)
```

If you are adding a code path that touches a Databricks resource and it doesn't
go through `resolve_effective_action()`, stop and reconsider the design.

Handler capability is **opt-in by protocol**, not duck-typing. A handler that
does not implement `SupportsTerminate` physically cannot be asked to terminate.
Do not reintroduce `hasattr(handler, "kill")`-style dispatch.

## Database

- No Alembic. Tables are created via `Base.metadata.create_all` at startup, and
  schema evolution goes in `app/db/migrate.py` as **idempotent** helpers
  (add column if missing, add index if missing, backfill).
- Local is SQLite (`backend/sentinel.db`), deployed is Lakebase/Postgres.
- Long scans must use **short-lived sessions**. Holding a connection across a
  multi-minute scan is how you get `SSL connection has been closed unexpectedly`
  and lose the whole run. Read the allowlist, close. Write findings in batches,
  close. Persist the summary, close.

## OPA

- Prefer the **embedded server** (`opa run --server` on an ephemeral port,
  started in the lifespan). It turns a ~25ms subprocess spawn per evaluation
  into a ~1ms HTTP call, which matters at thousands of evaluations per scan.
- Evaluate **one namespace call per resource** (`evaluate_namespace`), not one
  call per resource per policy.
- The CLI path still exists as a fallback and must stay off the event loop
  (`asyncio.to_thread`).

## Policies

Rego lives in git. `backend/policies/` is a working copy that
`services/policy_sync.py` rebuilds from the target branch — nothing writes a
policy there, and every change goes out as a pull request (see the root
`AGENTS.md`). Conventions are parsed by `policy_registry.py`:

- `rule_metadata` maps rule id -> object with `id`, `category`, `description`,
  `severity`, and optionally `requested_action`.
- `applies`, `violations[rule_id]`, and `rule_results` give per-rule PASS/FAIL.
- Policies emit `requested_action`, never `action`. Rego proposes; Python
  disposes.
- Every policy ships at `WARN`. Escalation is a per-rule `# METADATA` annotation
  and a reviewed PR.

## Testing

```bash
cd backend && source venv/bin/activate && pytest
pytest tests/unit/safety/ -v      # the suite that must never go red
```

- `tests/conftest.py` gives in-memory SQLite with per-test rollback and a
  `client` fixture that overrides `get_db`. Tests must never write to the real
  `backend/sentinel.db`.
- Mock at boundaries: fake handlers with async `discover()`, a fake OPA
  returning Rego-shaped dicts, `MagicMock()` workspace clients. Do not patch
  away the function under test.
