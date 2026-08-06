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

## A policy can only test what discovery collects

Every handler declares `discovered_fields`: the exact keys its `discover()`
returns, with a description. `app/services/resource_schema.py` gathers them, the
agent prompt is built from them, and `/policies/validate` warns when a policy
reads something outside that vocabulary.

This is not bookkeeping. **Rego treats a reference to a field that was never
supplied as simply not matching.** A rule about `idle_hours` on a resource type
whose handler never collects `idle_hours` does not error — it never fires, every
resource comes back compliant, and there is nothing on any screen to distinguish
that from a rule that ran and found nothing. Nine shipped policies were in
exactly that state via `idle_days`.

So:

- Adding a field to `discover()` means adding it to `discovered_fields` in the
  same change. A field the handler sets but does not declare will be flagged as
  unknown in every policy that uses it.
- Declaring a field the handler does not actually set is **worse** than omitting
  one, because it invites the rule that cannot work. Do not add speculative
  entries.
- Writing a rule for data nothing collects means changing the handler first.
  There is no policy-only version of that change.

`test_resource_schema.py` asserts every registered handler declares its fields,
and records where the shipped policies currently stand.

### Omit a field you could not determine

Where a value is unknown, leave the key off the resource rather than writing a
zero or an empty list. A rule reading a missing field falls back to its own
default and stays quiet, and `rule_diagnosis` can report the field as never
collected. A placeholder makes an unanswerable question look answered — an
`idle_days` of 0 says "in use", which is the opposite of what we know.

### The scanner is not an admin, and some data is only visible to one

Before writing a collector, check that the identity this runs as can actually
see the thing. Two failure modes, and the second is the dangerous one:

- The call raises, which is loud and gets handled.
- The call **succeeds and returns a filtered view**, which is silent.

Unity Catalog's `information_schema.table_privileges` and `volume_privileges`
are the live example. They look like the obvious source for "who can reach this
table" and they filter to the caller: unless you own the object, own its catalog
or schema, or are a metastore admin, you are shown only *your own* grants. A
scanner reading that gets a near-empty result, no error, and concludes the estate
is not over-shared. This was written, then removed. Do not add it back.

The same applies to the `system` catalog, which needs a `SELECT` grant only a
metastore admin can make, and to account-level SCIM data from a workspace-scoped
client.

When a field is out of reach, record it in `rule_diagnosis.BLOCKED_FIELDS` with
the access that would unblock it, rather than leaving the rules that read it
looking like queued engineering work. `needs_permission` and `not_exposed` exist
so the right person hears about it; a test asserts nothing sits in
`needs_discovery`, so a genuinely collectable field that nobody collected fails
the build.

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

### Renaming a policy

A policy's name is stored data. Allowlist exceptions, saved filters and
historical findings all reference it, so moving the file orphans them — silently,
because an exception that matches nothing just stops suppressing, which looks
like the rule tightening rather than like a break.

Never rename a policy file on its own. `services/policy_rename.py` is the only
correct route, and it does three things at once:

1. writes the file under the new name,
2. rewrites the `package` declaration, since OPA resolves by package and a
   mismatch leaves the policy loaded under its old name,
3. appends the old name to `custom.replaces` in the policy's own METADATA.

Step 3 is what keeps stored references working. It lives in the policy rather
than in a table in Python so the alias syncs with the file instead of waiting
for a deploy; `policy_registry.declared_aliases()` reads it, and a live policy
always beats an alias. `providers/opa/legacy_names.py` still holds the static
table from the original per-resource restructure — that one is historical, do
not add to it.

`services/policy_scaffold.py` generates new policies. Anything it produces must
stay Tier 1 and must only read fields in the resource's `discovered_fields`,
or the template teaches the exact mistake the field catalogue exists to catch.

## Testing

```bash
cd backend && source venv/bin/activate && pytest
pytest tests/safety/ -v           # the suite that must never go red
pytest -m safety                  # same tests, wherever they live
```

The Testing Center in the app runs the same suites in a subprocess, plus fixture
runs that put made-up resources through the real policies. Fixtures live in
`backend/fixtures/synthetic/`, and `POST /testing/capture` writes new ones from
the resource snapshots a real scan already recorded.

- `tests/conftest.py` gives in-memory SQLite with per-test rollback and a
  `client` fixture that overrides `get_db`. Tests must never write to the real
  `backend/sentinel.db`.
- Mock at boundaries: fake handlers with async `discover()`, a fake OPA
  returning Rego-shaped dicts, `MagicMock()` workspace clients. Do not patch
  away the function under test.
