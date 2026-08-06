# AGENTS.md

Guidance for AI coding agents (and humans) working in this repo. This is the
canonical agent guide. Nested `AGENTS.md` files add area-specific detail — the
nearest one to the file you're editing wins.

## Golden rule: non-destructive by default

**This outranks every other instruction in this file.** The Sentinel can
terminate production compute, delete service principals, and revoke access
across every workspace it can reach. A bug here is not a broken page, it is
someone's running job destroyed at 2am with no undo.

The system is built so that destruction is something you must deliberately opt
into at five independent points, not something you have to remember to turn off.
When working in this repo:

- **Never introduce a destructive default.** If an action is missing, unknown,
  malformed, or an evaluation raised, the answer is `WARN`. Absence of
  information must never produce destruction. This codebase previously had
  `action = result.get("action", "KILL")` — a policy that failed to parse killed
  the resource. Do not reintroduce that shape in any form.
- **Never call a destructive Databricks SDK method outside**
  `backend/app/providers/databricks/destructive.py`. That module asserts it was
  reached through a resolved `EffectiveAction`. A test walks the source tree to
  enforce this, and it is not a formality — it is the last structural barrier.
- **Never widen a policy's tier without saying so explicitly in the PR body.**
  Raising a rule from `WARN` to `REVOKE_ACCESS`, or anything to Tier 3, is the
  single highest-risk change you can make here. It belongs in its own PR with
  the blast radius stated.
- **Every action goes through `resolve_effective_action()`**
  (`backend/app/core/enforcement.py`). Scheduled scans, manual UI actions, MCP
  tools, the agent — all of them. If you are adding a new path that touches a
  resource and it does not call the chokepoint, the design is wrong.
- **New remediation should be reversible.** Prefer the Tier 2 verbs
  (`REVOKE_ACCESS`, `QUARANTINE`, `DISABLE`, `THROTTLE`) over Tier 3. Each ships
  with an undo and records prior state. Revoking access to an untagged
  production cluster achieves the governance goal without destroying work.

The action ladder lives in `backend/app/core/actions.py` and is the single
source of truth. Read it before touching anything in the enforcement path.

## Second rule: policies are stored in git, never on disk

The app is deployed as a Databricks App, which has an **ephemeral filesystem**.
Anything written at runtime is gone at the next restart. So:

- **`backend/policies/` is a working copy, not storage.** It is rebuilt from the
  target branch by `backend/app/services/policy_sync.py` at startup, on an
  interval, and on demand. It exists because OPA evaluates a directory of files
  and `opa inspect` parses that same directory — not because it is where
  policies live.
- **Nothing writes a policy or its `.md` except a pull request.** Editing,
  retiring, and explaining all end in a reviewable PR
  (`backend/app/api/v1/endpoints/policies.py`). There is no save endpoint, and
  adding one back would produce an edit that survives until the container
  recycles and then vanishes without a trace — which looks like it worked.
- **A policy and its English `.md` are committed together on one branch**, so a
  reviewer who cannot read Rego always sees the consequence change in the same
  diff.
- Unsubmitted work lives in the browser's `localStorage` (`src/store/policyStore.ts`)
  and is deliberately local: a draft nobody has reviewed is not a policy.

`backend/tests/unit/api/test_policy_writes.py` asserts the *absence* of the
write paths. Like the safety suite, a failure there is a design signal, not a
test to update.

## What this is

An **Enforcement Sentinel** for Databricks: it discovers resources across one or
more workspaces, evaluates each against OPA/Rego governance policies, records
findings, and — only when explicitly enabled — remediates them. Policies are
authored in the UI with an AI assistant, reviewed through GitHub PRs, and carry
structured metadata (policy ID, category, owner, requested action).

## Repo layout

| Path | What |
|---|---|
| `src/` | React + TypeScript SPA (Vite). See `src/AGENTS.md`. |
| `backend/` | FastAPI backend, scan engine, providers, agent. See `backend/AGENTS.md`. |
| `backend/policies/` | Working copy of the Rego policies + their English `.md` siblings, synced from git. |
| `docs/release-notes/` | User-facing release notes, one file per version. |
| `databricks.yml` | Bundle config / per-target env vars for deployment. |
| `dev.sh` | One-command local dev (backend + frontend). |

## Running locally

- **`./dev.sh`** starts backend (`:8000`) and frontend (`:5173`), creates the
  venv, installs deps, and tails to `backend.log` / `frontend.log`.
- You do **not** need to deploy to Databricks to run locally.
- **Check `backend.log` before finishing** any change that reloads FastAPI — a
  startup error there means the app isn't actually running, and a passing test
  run will not tell you.

## Golden rules (apply everywhere)

- **Use the logging library, never `print`.**
- **Never hardcode the app/brand name.** In-code defaults live in
  `backend/app/core/default_config.py`, exposed as `settings.BRANDING_*`. A
  Platform Admin can override them live.
- **Prefer no-code over hardcoding.** New configuration should be editable in
  Settings (`settings_store.py`) or set in `databricks.yml` — not baked into
  code. Config layers: in-code defaults → env (`.env` / `databricks.yml`) → DB
  overrides (Settings), applied at startup.
- **Read `settings.X` at call time**, not at import. DB overrides are applied
  after module import, so a module-level `FOO = settings.FOO` captures the
  pre-override value and silently ignores the admin's setting.
- **Venv gotcha:** Python libs are not globally installed. Activate
  `backend/venv` before running any `python` / `pytest` / scratch script.
- **Local DB** is SQLite at `backend/sentinel.db` (query it directly if useful);
  deployed uses Lakebase/Postgres.
- Only commit when explicitly asked.

## Keeping this file and the release notes current

Two files decay silently and are worth the small tax of updating in the same
change that makes them stale:

- **This file**, when you add a subsystem, change a golden rule, or move
  something a future agent would go looking for in the old place.
- **`docs/release-notes/`**, whenever app behavior changes in a way a user would
  notice — new page, changed default, new policy action, altered scan behavior.
  Add an entry to the current unreleased version file, or create the next
  version file if none is open. The UI surfaces these with a "Release Notes" badge,
  so an empty release notes page after a big change is a visible gap.

## Testing

- Backend: `cd backend && source venv/bin/activate && pytest`
- Frontend: `npm run build` (typecheck via `tsc`) and `npm run lint`
- The safety suite in `backend/tests/safety/` must never go red. Several of
  those tests are written to fail on a *future* careless change rather than on
  current behavior — if one breaks, the correct response is almost never to
  update the test.
- Policy changes want a fixture in `backend/fixtures/synthetic/` naming the rules
  that should and should not fire. `test_synthetic_estate.py` runs every
  committed fixture against the live policies, so a fixture is a regression test
  for the rule it describes. The Testing Center page, and the Tests tab in the
  Policy Editor, run the same thing on demand — the editor against your unsaved
  draft rather than the committed file.
- A rule with no fixture is an *untested* rule, not a passing one, and the two
  are indistinguishable on a green page. `/testing/coverage` reports which is
  which. 59 of 64 shipped rules currently have no fixture.
- **A rule may only test fields some handler actually collects.** Rego does not
  error on a reference to data that was never supplied — the rule silently never
  fires and every resource reads as compliant, permanently. Handlers declare
  `discovered_fields`; see `backend/AGENTS.md`. If a request needs data nobody
  gathers, the handler change comes first, and there is no policy-only shortcut.
