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

matching_exceptions(allowlist_records, resource_id) := [e |
	some e in allowlist_records
	e.resource_id == resource_id
]

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

has_approved_exception(allowlist_records, resource_id, is_viol, request_time) if {
	is_viol
	some exception in matching_exceptions(allowlist_records, resource_id)
	exception.status == "approved"
	is_valid_expiry(exception, request_time)
} else := false

has_pending_exception(allowlist_records, resource_id, is_viol, has_approved) if {
	is_viol
	not has_approved
	some exception in matching_exceptions(allowlist_records, resource_id)
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

resolve_reason(is_viol, has_approved, has_pending, allowlist_records, resource_id, request_time, violation_reasons) := exception.justification if {
	has_approved
	some exception in matching_exceptions(allowlist_records, resource_id)
	exception.status == "approved"
	is_valid_expiry(exception, request_time)
}

resolve_reason(is_viol, has_approved, has_pending, allowlist_records, resource_id, request_time, violation_reasons) := "Exception request is pending admin approval." if {
	has_pending
}

resolve_reason(is_viol, has_approved, has_pending, allowlist_records, resource_id, request_time, violation_reasons) := format_reasons(violation_reasons) if {
	is_viol
	not has_approved
	not has_pending
}

resolve_reason(is_viol, has_approved, has_pending, allowlist_records, resource_id, request_time, violation_reasons) := "Resource complied with policies." if {
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

rule_result(rule_id, meta, messages, allowlist_records, resource_id, request_time) := result if {
	failed := count(messages) > 0
	has_approved := has_approved_exception(allowlist_records, resource_id, failed, request_time)
	has_pending := has_pending_exception(allowlist_records, resource_id, failed, has_approved)

	result := {
		"rule": rule_id,
		"id": object.get(meta, "id", rule_id),
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

build_results(metadata, violations, allowlist_records, resource_id, request_time) := [result |
	some rule_id, meta in metadata
	result := rule_result(rule_id, meta, messages_for(violations, rule_id), allowlist_records, resource_id, request_time)
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

request_time := object.get(input, "request_time", 0)

# The entry point every policy uses.
results(metadata, violations) := build_results(
	metadata,
	violations,
	allowlist_records,
	resource_id,
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

summarize(metadata, violations) := {
	"is_violation": violated,
	"action": resolve_action(violated, has_approved, has_pending, safe_action),
	"reason": resolve_reason(
		violated,
		has_approved,
		has_pending,
		allowlist_records,
		resource_id,
		request_time,
		messages,
	),
	"severity": max_severity(results(metadata, violations)),
} if {
	messages := all_messages(violations)
	violated := is_violation(messages)
	has_approved := has_approved_exception(allowlist_records, resource_id, violated, request_time)
	has_pending := has_pending_exception(allowlist_records, resource_id, violated, has_approved)
}

not_applicable := {
	"is_violation": false,
	"action": "ALLOW",
	"reason": "Policy does not apply to this resource type.",
	"severity": "NONE",
}
