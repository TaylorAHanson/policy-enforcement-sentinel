# METADATA
# title: Cluster governance
# description: |
#   Rules for all-purpose and job compute. Covers isolation in production, cost
#   attribution, and idle spend.
#
#   Every rule here ships at WARN. That is not an oversight: a cluster with a
#   running notebook attached represents someone's unsaved work, and no rule in
#   this file is confident enough to be worth destroying it. THROTTLE and
#   TERMINATE are implemented and available -- raising a rule to either is a
#   deliberate edit, and TERMINATE additionally requires destructive: true plus
#   all five gates in app/core/enforcement.py.
# authors:
# - compute-platform@company.com
# custom:
#   owner: compute-platform
#   domain: compute
#   resource_type: cluster
package databricks.governance.clusters

import data.databricks.governance.common
import future.keywords.contains
import future.keywords.if
import future.keywords.in

rule_metadata := {
	"shared_interactive_in_prod": {
		"id": "SEC-CLU-001",
		"category": "security",
		"description": "Shared interactive clusters are not permitted in production. Shared access mode makes every attached user indistinguishable in audit logs and gives them each other's credentials in practice.",
		"severity": "HIGH",
		"requested_action": "WARN",
		"destructive": false,
	},
	"missing_compute_policy": {
		"id": "CTL-CLU-002",
		"category": "control",
		"description": "Clusters must be created from a compute policy. Unrestricted compute is how a workspace acquires a 64-node cluster nobody remembers asking for.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
	"missing_cost_tags": {
		"id": "CST-CLU-003",
		"category": "cost",
		"description": "Clusters must carry cost-center and owner tags so spend can be attributed and the owner can be reached.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
	"no_autotermination": {
		"id": "CST-CLU-004",
		"category": "cost",
		"description": "All-purpose clusters must set autotermination. A cluster left running overnight costs the same as one doing work.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
	"idle": {
		"id": "CST-CLU-005",
		"category": "cost",
		"description": "Clusters with no activity for an extended period should be reviewed and released.",
		"severity": "LOW",
		"requested_action": "WARN",
		"destructive": false,
		"escalate_after_days": 30,
	},
}

default applies := false

applies if {
	input.resource.type == "cluster"
}

violations.shared_interactive_in_prod contains msg if {
	applies
	input.resource.cluster_type == "interactive"
	input.resource.access_mode == "shared"
	input.workspace.environment == "prod"
	msg := "Shared interactive cluster in production. Use single-user or job compute so that activity is attributable."
}

violations.missing_compute_policy contains msg if {
	applies
	not input.resource.policy_id
	msg := "Cluster was created without a compute policy. Attach one so size and runtime are bounded."
}

violations.missing_cost_tags contains msg if {
	applies
	not input.resource.tags["cost-center"]
	msg := "Missing the 'cost-center' tag, so this cluster's spend cannot be attributed."
}

violations.missing_cost_tags contains msg if {
	applies
	not input.resource.tags.owner
	msg := "Missing the 'owner' tag, so there is nobody to notify about this cluster."
}

violations.no_autotermination contains msg if {
	applies
	input.resource.cluster_type == "interactive"
	object.get(input.resource, "autotermination_minutes", 0) == 0
	msg := "Autotermination is disabled. This cluster will run until somebody stops it by hand."
}

violations.idle contains msg if {
	applies
	idle := object.get(input.resource, "idle_days", 0)
	idle > 30
	msg := sprintf("No activity for %v days.", [idle])
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
