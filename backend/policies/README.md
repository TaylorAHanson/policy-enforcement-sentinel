# Policies

Open Policy Agent (OPA) Rego files defining what the Sentinel considers a
governance violation. One file per resource type, plus `common.rego` for the
shared logic.

For the wider governance architecture see [GOVERNANCE.md](../../docs/GOVERNANCE.md).

## Rego proposes, Python disposes

A policy cannot cause anything to happen. It produces a **requested action**,
and `app/core/enforcement.py` decides what actually happens after walking the
safety gates. This split is the reason a policy edit cannot delete anything: the
worst a bad policy can do is ask.

**Every rule in this directory ships at `WARN`.** That is deliberate and it is
not a placeholder. Stronger actions are implemented and available, but turning
one on is an explicit edit that a human makes with the blast radius in front of
them. See [Escalating a rule](#escalating-a-rule).

## File layout

Each policy declares four things:

| Name | Purpose |
| --- | --- |
| `rule_metadata` | One entry per rule: stable ID, category, severity, requested action, description |
| `applies` | Whether this policy is relevant to the resource in `input` |
| `violations[rule_id]` | Set of human-readable messages, keyed by rule |
| `rule_results` | Per-rule verdicts built by `common.results` |

`rule_results` carries a row for every rule, **including the ones that passed**,
so the scan record distinguishes "checked and compliant" from "never evaluated".
A resource that no policy applies to produces an empty list rather than a page
of spurious passes.

## Adding a rule

1. Add an entry to `rule_metadata` with a new unique ID (`SEC-`, `CST-`, or
   `CTL-` followed by a three-letter resource abbreviation and a number).
2. Add one or more `violations["your_rule_id"] contains msg if { ... }` bodies.
   Guard each with `applies`.
3. Write the message for the person who has to fix it. State what is wrong and
   why it matters, not which rule fired.
4. Run `opa fmt -w policies/ && opa check policies/`.
5. Add a case to `backend/tests/unit/policies/`.

Read every optional input field through `object.get(...)` with a default. A
missing field must not make a rule undefined, because an undefined rule is one
the engine cannot get a verdict from.

## Escalating a rule

Change `requested_action` in that rule's metadata. The ladder is defined in
`app/core/actions.py`:

| Tier | Actions | Notes |
| --- | --- | --- |
| 0 Observe | `FLAG` | Recorded, nothing else |
| 1 Notify | `WARN`, `ANNOTATE`, `CERTIFY` | Reaches a human, changes nothing |
| 2 Restrict | `REVOKE_ACCESS`, `QUARANTINE`, `DISABLE`, `THROTTLE`, `UNCERTIFY` | Reversible; the undo payload is stored before the change is made |
| 3 Destructive | `TERMINATE`, `DELETE` | Irreversible |

Anything above Tier 1 must also set `"destructive": true` on the rule, and the
safety suite fails the build if it does not. Tier 3 additionally needs all five
gates in `app/core/enforcement.py` to agree, one of which is that a human
confirmed that specific run.

A rule cannot escalate past what the resource's handler implements. Asking for
`REVOKE_ACCESS` on a resource type with no concept of access gets downgraded to
`WARN`, with the reason recorded on the finding.

## Allowlist exceptions

`common.rego` resolves exceptions before actions. An approved, unexpired
exception turns any verdict into `SKIPPED_ALLOWLIST`; a pending one becomes
`PENDING_EXCEPTION` so a request in flight is not enforced against.

An exception with `expires_at: null` never expires. Test for this with
`object.get(exception, "expires_at", null) == null` and not with
`not exception.expires_at` — JSON null is a *defined* value in Rego, so the
short spelling evaluates false and silently voids every open-ended exception.
That bug shipped once.

## Renamed policies

Policies used to be grouped by theme rather than resource type. Old names still
resolve through `app/providers/opa/legacy_names.py`; see `describe_migration()`
for the mapping.

## Commands

```bash
opa fmt -w policies/          # format (CI checks this)
opa check policies/           # type check
opa test policies/ tests/     # unit tests
opa eval -d policies/ -i /tmp/input.json 'data.databricks.governance.clusters.rule_results' --format pretty
```
