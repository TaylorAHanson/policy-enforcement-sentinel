# METADATA
# title: Databricks Apps governance
# description: |
#   Rules for Databricks Apps: where they may run, who can reach them, and
#   whether anyone still uses them.
#
#   An app is somebody's product. Deleting one because it looked idle over a
#   holiday period is the kind of mistake that ends a governance programme, so
#   these rules warn and let a human decide. REVOKE_ACCESS is implemented for
#   the sharing rule if an operator wants automatic containment.
# authors:
# - platform-governance@company.com
# custom:
#   owner: platform-governance
#   domain: apps
#   resource_type: app
package databricks.governance.apps

import data.databricks.governance.common
import future.keywords.contains
import future.keywords.if
import future.keywords.in

rule_metadata := {
	"unreviewed_in_enterprise_prod": {
		"id": "SEC-APP-001",
		"category": "security",
		"description": "Apps in enterprise production must have a documented risk review. Production apps typically hold service credentials and read real data.",
		"severity": "HIGH",
		"requested_action": "WARN",
		"destructive": false,
	},
	"shared_with_all_users": {
		"id": "SEC-APP-002",
		"category": "security",
		"description": "Apps must not be shared with all users. An app runs with its service principal's permissions, so sharing the app shares that access.",
		"severity": "HIGH",
		"requested_action": "WARN",
		"destructive": false,
	},
	"idle": {
		"id": "CST-APP-003",
		"category": "cost",
		"description": "Apps nobody has opened in a long time hold compute. Stopping them is reversible; confirm with the owner first.",
		"severity": "LOW",
		"requested_action": "WARN",
		"destructive": false,
		"escalate_after_days": 30,
	},
	"missing_cost_tags": {
		"id": "CST-APP-004",
		"category": "cost",
		"description": "Apps must carry cost-center and owner tags.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
}

default applies := false

applies if {
	input.resource.type == "app"
}

violations.unreviewed_in_enterprise_prod contains msg if {
	applies
	input.workspace.type == "enterprise"
	input.workspace.environment == "prod"
	not object.get(input.resource, "risk_review_id", false)
	msg := "App runs in enterprise production without a recorded risk review."
}

violations.shared_with_all_users contains msg if {
	applies
	"ALL_USERS" in object.get(input.resource, "shared_with", [])
	msg := "App is shared with all users, granting everyone the effective permissions of its service principal."
}

violations.idle contains msg if {
	applies
	idle := object.get(input.resource, "idle_days", 0)
	idle > 30
	msg := sprintf("Nobody has accessed this app in %v days.", [idle])
}

violations.missing_cost_tags contains msg if {
	applies
	not input.resource.tags["cost-center"]
	msg := "Missing the 'cost-center' tag, so this app's spend cannot be attributed."
}

violations.missing_cost_tags contains msg if {
	applies
	not input.resource.tags.owner
	msg := "Missing the 'owner' tag, so there is nobody to notify about this app."
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
