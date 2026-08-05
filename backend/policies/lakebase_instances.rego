# METADATA
# title: Lakebase instance governance
# description: |
#   Rules for Lakebase (managed Postgres) instances: capacity, retention, and
#   idle spend.
#
#   These are databases holding live application state. The Lakebase handler
#   deliberately implements no modifying action at all -- not even a reversible
#   one -- so every rule here is advisory by construction, and the chokepoint
#   will downgrade anything stronger to a notification because the capability
#   simply does not exist.
# authors:
# - platform-governance@company.com
# custom:
#   owner: platform-governance
#   domain: data
#   resource_type: lakebase_instance
package databricks.governance.lakebase_instances

import data.databricks.governance.common
import future.keywords.contains
import future.keywords.if
import future.keywords.in

rule_metadata := {
	"oversized_capacity": {
		"id": "CST-LKB-001",
		"category": "cost",
		"description": "Instance capacity should match observed load. Oversized instances bill for capacity nobody is using.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
	"short_retention": {
		"id": "CTL-LKB-002",
		"category": "reliability",
		"description": "Production instances must keep at least seven days of point-in-time recovery. Retention is the difference between an incident and a data loss event.",
		"severity": "HIGH",
		"requested_action": "WARN",
		"destructive": false,
	},
	"idle": {
		"id": "CST-LKB-003",
		"category": "cost",
		"description": "Instances with no connections for an extended period should be reviewed.",
		"severity": "LOW",
		"requested_action": "WARN",
		"destructive": false,
		"escalate_after_days": 30,
	},
	"no_owner": {
		"id": "CTL-LKB-004",
		"category": "control",
		"description": "Lakebase instances must have an identifiable owner.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
}

default applies := false

applies if {
	input.resource.type == "lakebase_instance"
}

violations.oversized_capacity contains msg if {
	applies
	capacity := object.get(input.resource, "capacity_units", 0)
	capacity > 8
	object.get(input.resource, "peak_connection_pct", 100) < 20
	msg := sprintf("Provisioned at %v capacity units but peak connection use is under 20%%.", [capacity])
}

violations.short_retention contains msg if {
	applies
	input.workspace.environment == "prod"
	retention := object.get(input.resource, "retention_days", 0)
	retention < 7
	msg := sprintf("Point-in-time recovery retention is %v days; production requires at least 7.", [retention])
}

violations.idle contains msg if {
	applies
	idle := object.get(input.resource, "idle_days", 0)
	idle > 30
	msg := sprintf("No client connections in %v days.", [idle])
}

violations.no_owner contains msg if {
	applies
	not object.get(input.resource, "owner", false)
	msg := "No owner recorded for this Lakebase instance."
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
