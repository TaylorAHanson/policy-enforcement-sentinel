# METADATA
# title: SQL warehouse governance
# description: |
#   Rules for SQL warehouses: compute policy coverage, autostop, scaling
#   ceilings, and cost attribution.
#
#   Warehouses are shared infrastructure -- terminating one disconnects every
#   dashboard and BI tool pointed at it, usually without warning to the people
#   using them. These rules warn. THROTTLE (lowering the cluster ceiling and
#   autostop, reversible) is implemented for operators who want teeth here.
# authors:
# - data-platform@company.com
# custom:
#   owner: data-platform
#   domain: sql
#   resource_type: sql_warehouse
package databricks.governance.sql_warehouses

import data.databricks.governance.common
import future.keywords.contains
import future.keywords.if
import future.keywords.in

rule_metadata := {
	"missing_compute_policy": {
		"id": "CTL-WHS-001",
		"category": "control",
		"description": "Production warehouses must use a compute policy so size and scaling are bounded.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
	"no_autostop": {
		"id": "CST-WHS-002",
		"category": "cost",
		"description": "Warehouses must stop when idle. Serverless warehouses bill by the second and do not stop on their own.",
		"severity": "HIGH",
		"requested_action": "WARN",
		"destructive": false,
	},
	"excessive_scaling": {
		"id": "CST-WHS-003",
		"category": "cost",
		"description": "Warehouse maximum cluster count should be justified. A high ceiling turns one runaway query into a large invoice.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
	"missing_cost_tags": {
		"id": "CST-WHS-004",
		"category": "cost",
		"description": "Warehouses must carry cost-center and owner tags.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
	"idle": {
		"id": "CST-WHS-005",
		"category": "cost",
		"description": "Warehouses with no queries for an extended period should be reviewed.",
		"severity": "LOW",
		"requested_action": "WARN",
		"destructive": false,
		"escalate_after_days": 60,
	},
}

default applies := false

applies if {
	input.resource.type == "sql_warehouse"
}

violations.missing_compute_policy contains msg if {
	applies
	input.workspace.environment == "prod"
	not input.resource.policy_id
	msg := "Production warehouse has no compute policy attached."
}

violations.no_autostop contains msg if {
	applies
	object.get(input.resource, "auto_stop_mins", 0) == 0
	msg := "Autostop is disabled. This warehouse bills continuously whether or not anyone is querying."
}

violations.excessive_scaling contains msg if {
	applies
	max_clusters := object.get(input.resource, "max_num_clusters", 1)
	max_clusters > 10
	msg := sprintf("Scales to %v clusters. Confirm that ceiling is intentional.", [max_clusters])
}

violations.missing_cost_tags contains msg if {
	applies
	not input.resource.tags["cost-center"]
	msg := "Missing the 'cost-center' tag, so this warehouse's spend cannot be attributed."
}

violations.missing_cost_tags contains msg if {
	applies
	not input.resource.tags.owner
	msg := "Missing the 'owner' tag, so there is nobody to notify about this warehouse."
}

violations.idle contains msg if {
	applies
	idle := object.get(input.resource, "idle_days", 0)
	idle > 60
	msg := sprintf("No queries in %v days.", [idle])
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
