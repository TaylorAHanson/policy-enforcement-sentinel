# METADATA
# title: Common governance helpers
# description: |
#   Shared logic every policy builds on: allowlist exception resolution, action
#   and severity resolution, and the per-rule result shape the scan engine
#   consumes.
#
#   Rego proposes; Python disposes. Nothing here decides what happens to a
#   resource — it produces a *requested* action, which app/core/enforcement.py
#   then resolves against the safety gates. When in doubt this file returns
#   WARN, and it is never correct to change that to something stronger.
# authors:
# - platform-governance@company.com
# custom:
#   owner: platform-governance
#   domain: shared
package databricks.governance.common

import future.keywords.contains
import future.keywords.if
import future.keywords.in

# The floor. Every path that cannot determine an action lands here. Python
# applies the same floor independently — deliberate redundancy, because these
# are the two places a mistake would be most expensive.
safe_action := "WARN"

# --- Allowlist exceptions ---------------------------------------------------
#
# Two shapes of exception, and one rule that governs both:
#
#   **An empty selector matches nothing.**
#
# That is the same rule as the enforcement defaults, for the same reason. A
# selector left blank is an absence of intent, and reading an absence as
# "everything" turns a half-filled form into a waiver of every rule on every
# resource in the estate — silently, because a suppressed finding looks exactly
# like a resource that complied.
#
# A `resource` exception names one resource and waives every rule that fails for
# it. This is the original shape and the default, so a record written before
# patterns existed — or by anything that does not know about them — keeps
# behaving exactly as it did.
#
# A `pattern` exception waives one rule for one resource type. It is broader by
# construction, so both selectors are required to be present and non-blank here,
# in addition to being required by the API. Two independent checks, because this
# is the one place where getting it wrong is unbounded.

exception_match_type(e) := object.get(e, "match_type", "resource")

matches(e, resource_id, _, _) if {
	exception_match_type(e) == "resource"
	target := object.get(e, "resource_id", "")
	is_string(target)
	target != ""
	target == resource_id
}

matches(e, _, resource_type, rule_id) if {
	exception_match_type(e) == "pattern"

	wanted_type := object.get(e, "resource_type", "")
	is_string(wanted_type)
	wanted_type != ""
	wanted_type == resource_type

	wanted_rule := object.get(e, "rule_id", "")
	is_string(wanted_rule)
	wanted_rule != ""
	wanted_rule == rule_id
}

matching_exceptions(allowlist_records, resource_id, resource_type, rule_id) := [e |
	some e in allowlist_records
	matches(e, resource_id, resource_type, rule_id)
]

# --- Optional fields --------------------------------------------------------

# Whether an optional field actually holds something.
#
# The trap this exists for, which has now caught two rules in this repository:
# `not input.resource.policy_id` reads as "there is no compute policy" and does
# not mean that. JSON null is a *defined* value in Rego, so the expression is
# truthy and the negation fails — and the Databricks SDK returns null, not an
# absent key, for a cluster with no policy. The rule never fired in production
# and looked like a clean bill of health.
#
# Use this for anything an API may return as null. `not input.resource.thing` is
# only correct when the key is genuinely absent.
is_set(value) if {
	value != null
	value != ""
}

# Whether nobody is recorded as owning a resource.
#
# The companion trap to `is_set`, and it caught five rules. Each was written as
# `not object.get(input.resource, "owner", false)`, which fires only when the
# key is missing or literally false. It never is: every handler defaults the
# field to the string "unknown" precisely because the API named nobody, so the
# five rules that exist to find unowned resources found none, ever.
#
# Absence therefore arrives in four shapes, and all four mean the same thing.
no_owner(resource) if {
	not is_set(object.get(resource, "owner", null))
}

no_owner(resource) if {
	lower(object.get(resource, "owner", "")) == "unknown"
}

# --- Allowlist expiry -------------------------------------------------------

# A null expiry means "never expires".
#
# The obvious spelling, `not exception.expires_at`, does not say that: JSON null
# is a *defined* value in Rego, so the expression is false and an exception with
# no expiry date silently stopped applying. Every allowlist entry created
# without an end date was being ignored. Test for null explicitly.
is_valid_expiry(exception, current_time) if {
	object.get(exception, "expires_at", null) == null
}

is_valid_expiry(exception, current_time) if {
	expires := object.get(exception, "expires_at", null)
	expires != null
	expires > current_time
}

has_approved_exception(allowlist_records, resource_id, resource_type, rule_id, is_viol, request_time) if {
	is_viol
	some exception in matching_exceptions(allowlist_records, resource_id, resource_type, rule_id)
	exception.status == "approved"
	is_valid_expiry(exception, request_time)
} else := false

has_pending_exception(allowlist_records, resource_id, resource_type, rule_id, is_viol, has_approved) if {
	is_viol
	not has_approved
	some exception in matching_exceptions(allowlist_records, resource_id, resource_type, rule_id)
	exception.status == "pending"
} else := false

# --- Action resolution ------------------------------------------------------

# An action must always be a non-empty string. A policy that omits its requested
# action, or sets it to null, gets WARN rather than an undefined value that
# Python would have to interpret — and interpreting an absence is exactly how
# the old `get("action", "KILL")` default came about.
guarded_action(requested) := requested if {
	is_string(requested)
	requested != ""
} else := safe_action

resolve_action(is_viol, has_approved, has_pending, requested) := "SKIPPED_ALLOWLIST" if {
	has_approved
}

resolve_action(is_viol, has_approved, has_pending, requested) := "PENDING_EXCEPTION" if {
	has_pending
}

resolve_action(is_viol, has_approved, has_pending, requested) := guarded_action(requested) if {
	is_viol
	not has_approved
	not has_pending
}

resolve_action(is_viol, has_approved, has_pending, requested) := "ALLOW" if {
	not is_viol
}

# --- Severity ---------------------------------------------------------------

resolve_severity(is_viol, has_approved, has_pending, default_severity) := "NONE" if {
	has_approved
}

resolve_severity(is_viol, has_approved, has_pending, default_severity) := "MEDIUM" if {
	has_pending
}

resolve_severity(is_viol, has_approved, has_pending, default_severity) := default_severity if {
	is_viol
	not has_approved
	not has_pending
}

resolve_severity(is_viol, has_approved, has_pending, default_severity) := "NONE" if {
	not is_viol
}

# --- Reasons ----------------------------------------------------------------

is_violation(violation_reasons) if {
	count(violation_reasons) > 0
} else := false

format_reasons(reasons) := formatted if {
	sorted_reasons := sort([r | some r in reasons])
	formatted := concat(" ", [sprintf("%d. %s", [i + 1, msg]) |
		some i, msg in sorted_reasons
	])
}

resolve_reason(is_viol, has_approved, has_pending, allowlist_records, resource_id, resource_type, rule_id, request_time, violation_reasons) := exception.justification if {
	has_approved
	some exception in matching_exceptions(allowlist_records, resource_id, resource_type, rule_id)
	exception.status == "approved"
	is_valid_expiry(exception, request_time)
}

resolve_reason(is_viol, has_approved, has_pending, allowlist_records, resource_id, resource_type, rule_id, request_time, violation_reasons) := "Exception request is pending admin approval." if {
	has_pending
}

resolve_reason(is_viol, has_approved, has_pending, allowlist_records, resource_id, resource_type, rule_id, request_time, violation_reasons) := format_reasons(violation_reasons) if {
	is_viol
	not has_approved
	not has_pending
}

resolve_reason(is_viol, has_approved, has_pending, allowlist_records, resource_id, resource_type, rule_id, request_time, violation_reasons) := "Resource complied with policies." if {
	not is_viol
}

# --- Per-rule results -------------------------------------------------------
#
# The scan engine records one finding per rule, pass or fail, so that "checked
# and compliant" is distinguishable from "never evaluated". Each policy hands
# its rule_metadata and violations to build_results and gets that shape back.

messages_for(violations, rule_id) := sort([m |
	some m in object.get(violations, rule_id, set())
])

rule_result(rule_id, meta, messages, allowlist_records, resource_id, resource_type, request_time) := result if {
	failed := count(messages) > 0

	# A pattern exception is matched on the public ID (CST-CLU-005), not the
	# rule's name in the file. That is the identifier shown in the UI, cited in
	# findings, and picked from a list when someone writes an exception — and
	# unlike the rule name, it is stable across a rename.
	public_id := object.get(meta, "id", rule_id)

	has_approved := has_approved_exception(allowlist_records, resource_id, resource_type, public_id, failed, request_time)
	has_pending := has_pending_exception(allowlist_records, resource_id, resource_type, public_id, failed, has_approved)

	result := {
		"rule": rule_id,
		"id": public_id,
		"category": object.get(meta, "category", "control"),
		"description": object.get(meta, "description", ""),
		"passed": count(messages) == 0,
		"messages": messages,
		"severity": resolve_severity(failed, has_approved, has_pending, object.get(meta, "severity", "MEDIUM")),
		"requested_action": resolve_action(failed, has_approved, has_pending, object.get(meta, "requested_action", safe_action)),
		"destructive": object.get(meta, "destructive", false),
		"escalate_after_days": object.get(meta, "escalate_after_days", 0),
	}
}

build_results(metadata, violations, allowlist_records, resource_id, resource_type, request_time) := [result |
	some rule_id, meta in metadata
	result := rule_result(rule_id, meta, messages_for(violations, rule_id), allowlist_records, resource_id, resource_type, request_time)
]

all_messages(violations) := [msg |
	some rule_id, _ in violations
	some msg in object.get(violations, rule_id, set())
]

# --- Input accessors --------------------------------------------------------
#
# `input` is global in Rego, so reading it here rather than threading it through
# every policy removes about fifteen lines of identical boilerplate per file --
# and with it the chance of one file getting the boilerplate subtly wrong.
# Every read is defaulted: a malformed input document must not make a policy
# undefined, because an undefined policy is one the engine cannot get an action
# from.

allowlist_records := object.get(input, "allowlist_records", [])

resource_id := object.get(object.get(input, "resource", {}), "id", "")

# Defaults to "" for the same reason every accessor here does, and that default
# is load-bearing rather than defensive: a pattern exception requires a non-blank
# resource_type to match, so an input document with no resource type cannot be
# waived by one.
resource_type := object.get(object.get(input, "resource", {}), "type", "")

request_time := object.get(input, "request_time", 0)

# The entry point every policy uses.
results(metadata, violations) := build_results(
	metadata,
	violations,
	allowlist_records,
	resource_id,
	resource_type,
	request_time,
)

# --- Legacy aggregate summary ----------------------------------------------
#
# One action and severity for the whole policy, which is what the pre-per-rule
# API returned. Kept so older consumers keep working; the per-rule results are
# what the scan engine actually acts on.
#
# The aggregate action is deliberately WARN whenever anything failed, rather
# than the strongest action any rule asked for. Collapsing several rules into
# one action loses the context that justified the strongest of them, and this
# path has no caller that needs to act -- so it reports rather than escalates.

severity_rank := {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

rank_to_severity := {0: "NONE", 1: "LOW", 2: "MEDIUM", 3: "HIGH", 4: "CRITICAL"}

max_severity(results) := rank_to_severity[top] if {
	ranks := [rank |
		some r in results
		rank := object.get(severity_rank, r.severity, 0)
	]
	count(ranks) > 0
	top := max(ranks)
} else := "NONE"

# The empty rule ID below is deliberate. This path collapses every rule into one
# verdict, so there is no single rule a pattern exception could be about — and a
# blank rule ID matches no pattern, which is exactly the right answer. Only
# resource exceptions apply here. The per-rule results, which are what the scan
# engine acts on, see patterns normally.
summarize(metadata, violations) := {
	"is_violation": violated,
	"action": resolve_action(violated, has_approved, has_pending, safe_action),
	"reason": resolve_reason(
		violated,
		has_approved,
		has_pending,
		allowlist_records,
		resource_id,
		resource_type,
		"",
		request_time,
		messages,
	),
	"severity": max_severity(results(metadata, violations)),
} if {
	messages := all_messages(violations)
	violated := is_violation(messages)
	has_approved := has_approved_exception(allowlist_records, resource_id, resource_type, "", violated, request_time)
	has_pending := has_pending_exception(allowlist_records, resource_id, resource_type, "", violated, has_approved)
}

not_applicable := {
	"is_violation": false,
	"action": "ALLOW",
	"reason": "Policy does not apply to this resource type.",
	"severity": "NONE",
}
