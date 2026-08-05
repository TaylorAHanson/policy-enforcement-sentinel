# METADATA
# title: Workspace and environment governance
# description: |
#   Workspace-level rules: identity federation, legacy access paths, and
#   dormant ad-hoc workspaces.
#
#   These findings describe a whole workspace, so there is no per-resource
#   remediation to apply and no handler behind them. They are reports for
#   platform administrators.
# authors:
# - platform-governance@company.com
# custom:
#   owner: platform-governance
#   domain: workspace
#   resource_type: workspace
package databricks.governance.workspaces

import data.databricks.governance.common
import future.keywords.contains
import future.keywords.if
import future.keywords.in

rule_metadata := {
	"dormant_adhoc": {
		"id": "CST-WKS-001",
		"category": "cost",
		"description": "Ad-hoc workspaces with no activity should be archived. Every live workspace is another surface to patch and audit.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
		"escalate_after_days": 90,
	},
	"no_unity_catalog": {
		"id": "CTL-WKS-002",
		"category": "control",
		"description": "Workspaces must be attached to a Unity Catalog metastore. Without one there is no cross-workspace lineage or access model.",
		"severity": "HIGH",
		"requested_action": "WARN",
		"destructive": false,
	},
	"pats_enabled_in_prod": {
		"id": "SEC-WKS-003",
		"category": "security",
		"description": "Personal access tokens should be disabled in enterprise production except for break-glass accounts. PATs do not expire on offboarding.",
		"severity": "HIGH",
		"requested_action": "WARN",
		"destructive": false,
	},
	"no_ip_access_list": {
		"id": "SEC-WKS-004",
		"category": "security",
		"description": "Production workspaces should restrict access by IP range.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
}

default applies := false

applies if {
	input.resource.type == "workspace"
}

violations.dormant_adhoc contains msg if {
	applies
	input.workspace.type == "ad-hoc"
	idle := object.get(input.resource, "idle_days", 0)
	idle > 90
	msg := sprintf("No interactive sessions or job runs in %v days.", [idle])
}

violations.no_unity_catalog contains msg if {
	applies
	object.get(input.resource, "metastore_id", "") == ""
	msg := "Workspace is not attached to a Unity Catalog metastore."
}

violations.pats_enabled_in_prod contains msg if {
	applies
	input.workspace.type == "enterprise"
	input.workspace.environment == "prod"
	object.get(input.resource, "pat_enabled", false) == true
	msg := "Personal access tokens are enabled in an enterprise production workspace."
}

violations.no_ip_access_list contains msg if {
	applies
	input.workspace.environment == "prod"
	count(object.get(input.resource, "ip_access_lists", [])) == 0
	msg := "No IP access list configured on a production workspace."
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
