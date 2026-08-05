# METADATA
# title: Service principal governance
# description: |
#   Rules for service principals: dormancy, over-entitlement, and ownership.
#
#   Deleting a service principal breaks every job, pipeline, and app that
#   authenticates as it, often in ways that only surface at the next scheduled
#   run. Dormancy signals are also the least reliable data the scanner collects.
#   These rules warn. DISABLE (deactivating the principal, reversible) is
#   implemented and is the right escalation if one is wanted -- not DELETE.
# authors:
# - identity-platform@company.com
# custom:
#   owner: identity-platform
#   domain: identity
#   resource_type: service_principal
package databricks.governance.service_principals

import data.databricks.governance.common
import future.keywords.contains
import future.keywords.if
import future.keywords.in

rule_metadata := {
	"dormant": {
		"id": "SEC-SPN-001",
		"category": "security",
		"description": "Service principals with no activity for an extended period should be deactivated. A dormant principal is a live credential nobody is watching.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
		"escalate_after_days": 90,
	},
	"account_admin": {
		"id": "SEC-SPN-002",
		"category": "security",
		"description": "Service principals should not hold account admin. Automation that can grant itself anything cannot be meaningfully audited.",
		"severity": "CRITICAL",
		"requested_action": "WARN",
		"destructive": false,
	},
	"no_owner_tag": {
		"id": "CTL-SPN-003",
		"category": "control",
		"description": "Service principals must record a human or team owner, so there is somebody to ask before it is disabled.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
	"stale_secret": {
		"id": "SEC-SPN-004",
		"category": "security",
		"description": "OAuth secrets should be rotated. A secret older than a year has usually outlived the people who knew where it was stored.",
		"severity": "HIGH",
		"requested_action": "WARN",
		"destructive": false,
	},
}

default applies := false

applies if {
	input.resource.type == "service_principal"
}

violations.dormant contains msg if {
	applies
	idle := object.get(input.resource, "idle_days", 0)
	idle > 90
	msg := sprintf("No successful authentication or workload activity in %v days.", [idle])
}

violations.account_admin contains msg if {
	applies
	"account_admin" in object.get(input.resource, "entitlements", [])
	msg := "Holds the account admin entitlement."
}

violations.no_owner_tag contains msg if {
	applies
	not object.get(input.resource, "owner", false)
	msg := "No owner recorded for this service principal."
}

violations.stale_secret contains msg if {
	applies
	age := object.get(input.resource, "secret_age_days", 0)
	age > 365
	msg := sprintf("OAuth secret is %v days old and has not been rotated.", [age])
}

default rule_results := []

rule_results := common.results(rule_metadata, violations) if {
	applies
}

summary := common.summarize(rule_metadata, violations) if {
	applies
} else := common.not_applicable

action := summary.action

is_violation := summary.is_violation

reason := summary.reason

severity := summary.severity
