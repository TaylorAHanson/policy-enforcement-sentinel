# METADATA
# title: Dashboard governance
# description: |
#   Rules for AI/BI dashboards, with an emphasis on the combination that
#   actually leaks data: embedded credentials plus broad sharing.
#
#   A dashboard published with embedded credentials runs its queries as its
#   owner, so sharing it with everyone shares the owner's data access with
#   everyone. That is the one rule here worth escalating, and REVOKE_ACCESS
#   (reversible, with the prior ACL stored as an undo payload) is implemented
#   for it. It still ships at WARN.
# authors:
# - data-platform@company.com
# custom:
#   owner: data-platform
#   domain: bi
#   resource_type: dashboard
package databricks.governance.dashboards

import data.databricks.governance.common
import future.keywords.contains
import future.keywords.if
import future.keywords.in

rule_metadata := {
	"embedded_credentials_shared_broadly": {
		"id": "SEC-DSH-001",
		"category": "security",
		"description": "Dashboards with embedded credentials must not be shared with all users. The dashboard runs queries as its publisher, so broad sharing hands out the publisher's data access.",
		"severity": "CRITICAL",
		"requested_action": "WARN",
		"destructive": false,
	},
	"published_without_owner": {
		"id": "CTL-DSH-002",
		"category": "control",
		"description": "Published dashboards must have an identifiable owner.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
	"stale": {
		"id": "CTL-DSH-003",
		"category": "reliability",
		"description": "Dashboards nobody has viewed in months are usually stale, and stale dashboards get quoted in meetings as though they are current.",
		"severity": "LOW",
		"requested_action": "WARN",
		"destructive": false,
		"escalate_after_days": 90,
	},
}

default applies := false

applies if {
	input.resource.type == "dashboard"
}

violations.embedded_credentials_shared_broadly contains msg if {
	applies
	input.resource.uses_embedded_credentials == true
	"ALL_USERS" in object.get(input.resource, "shared_with", [])
	msg := "Dashboard embeds its publisher's credentials and is shared with all users. Everyone who opens it queries as the publisher."
}

violations.published_without_owner contains msg if {
	applies
	object.get(input.resource, "is_published", false) == true
	not object.get(input.resource, "owner", false)
	msg := "Published dashboard has no owner recorded."
}

violations.stale contains msg if {
	applies
	idle := object.get(input.resource, "idle_days", 0)
	idle > 90
	msg := sprintf("Not viewed in %v days; its numbers may no longer be current.", [idle])
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
