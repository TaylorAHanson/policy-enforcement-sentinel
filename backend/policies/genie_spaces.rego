# METADATA
# title: Genie space governance
# description: |
#   Rules for Genie spaces. A Genie space is a natural-language interface onto
#   whatever tables it has been pointed at, which makes its sharing settings and
#   its table scope the whole of its security posture.
# authors:
# - data-platform@company.com
# custom:
#   owner: data-platform
#   domain: ai
#   resource_type: genie_space
package databricks.governance.genie_spaces

import data.databricks.governance.common
import future.keywords.contains
import future.keywords.if
import future.keywords.in

rule_metadata := {
	"unreviewed_in_enterprise_prod": {
		"id": "SEC-GEN-001",
		"category": "security",
		"description": "Genie spaces in enterprise production must have a documented risk review.",
		"severity": "HIGH",
		"requested_action": "WARN",
		"destructive": false,
	},
	"shared_with_all_users": {
		"id": "SEC-GEN-002",
		"category": "security",
		"description": "Genie spaces must not be shared with all users. Natural-language access to a table set is still access to that table set.",
		"severity": "HIGH",
		"requested_action": "WARN",
		"destructive": false,
	},
	"no_curated_tables": {
		"id": "CTL-GEN-003",
		"category": "control",
		"description": "Genie spaces must declare the tables they cover. An unscoped space answers questions from whatever it can reach.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
	"idle": {
		"id": "CST-GEN-004",
		"category": "cost",
		"description": "Unused Genie spaces should be reviewed and retired.",
		"severity": "LOW",
		"requested_action": "WARN",
		"destructive": false,
		"escalate_after_days": 60,
	},
}

default applies := false

applies if {
	input.resource.type == "genie_space"
}

violations.unreviewed_in_enterprise_prod contains msg if {
	applies
	input.workspace.type == "enterprise"
	input.workspace.environment == "prod"
	not object.get(input.resource, "risk_review_id", false)
	msg := "Genie space runs in enterprise production without a recorded risk review."
}

violations.shared_with_all_users contains msg if {
	applies
	"ALL_USERS" in object.get(input.resource, "shared_with", [])
	msg := "Genie space is shared with all users."
}

violations.no_curated_tables contains msg if {
	applies
	count(object.get(input.resource, "table_identifiers", [])) == 0
	msg := "No curated table set is declared for this Genie space."
}

violations.idle contains msg if {
	applies
	idle := object.get(input.resource, "idle_days", 0)
	idle > 60
	msg := sprintf("No questions asked in %v days.", [idle])
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
