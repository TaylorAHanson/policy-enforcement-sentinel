# METADATA
# title: Notebook governance
# description: |
#   Rules for notebooks, aimed at the two things that actually cause incidents:
#   secrets pasted into source, and production logic living in somebody's
#   personal folder where it is neither reviewed nor backed up.
#
#   Notebooks are source code and are frequently the only copy. Nothing in this
#   file will ever do more than warn, and the notebook handler deliberately
#   implements no reversible action at all.
# authors:
# - data-platform@company.com
# custom:
#   owner: data-platform
#   domain: workspace
#   resource_type: notebook
package databricks.governance.notebooks

import data.databricks.governance.common
import future.keywords.contains
import future.keywords.if
import future.keywords.in

rule_metadata := {
	"hardcoded_secret": {
		"id": "SEC-NBK-001",
		"category": "security",
		"description": "Notebooks must not contain hardcoded credentials. Use secret scopes; a token in a notebook is a token in version control and in every export of it.",
		"severity": "CRITICAL",
		"requested_action": "WARN",
		"destructive": false,
	},
	"prod_logic_in_personal_folder": {
		"id": "CTL-NBK-002",
		"category": "control",
		"description": "Notebooks scheduled in production must live in a shared, source-controlled folder rather than a personal one.",
		"severity": "HIGH",
		"requested_action": "WARN",
		"destructive": false,
	},
	"not_source_controlled": {
		"id": "CTL-NBK-003",
		"category": "control",
		"description": "Notebooks driving production workloads should be backed by a Git folder.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
}

default applies := false

applies if {
	input.resource.type == "notebook"
}

violations.hardcoded_secret contains msg if {
	applies
	some finding in object.get(input.resource, "secret_scan_findings", [])
	msg := sprintf("Possible hardcoded credential: %v.", [finding])
}

violations.prod_logic_in_personal_folder contains msg if {
	applies
	input.workspace.environment == "prod"
	object.get(input.resource, "is_scheduled", false) == true
	startswith(object.get(input.resource, "path", ""), "/Users/")
	msg := "Scheduled in production from a personal folder, where it is invisible to code review and lost if the account is deprovisioned."
}

violations.not_source_controlled contains msg if {
	applies
	object.get(input.resource, "is_scheduled", false) == true
	object.get(input.resource, "in_git_folder", false) == false
	msg := "Scheduled notebook is not in a Git folder, so there is no history of what changed."
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
