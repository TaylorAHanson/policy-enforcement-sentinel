# METADATA
# title: Model serving endpoint governance
# description: |
#   Rules for model serving endpoints: cost attribution, scale-to-zero, access
#   scope, and inference logging.
#
#   Foundation model endpoints provisioned by Databricks are exempt from the
#   tagging rules -- they are not customer-created and cannot be tagged, and
#   flagging them every scan trains people to ignore the report.
# authors:
# - ml-platform@company.com
# custom:
#   owner: ml-platform
#   domain: ai
#   resource_type: model_serving_endpoint
package databricks.governance.model_serving_endpoints

import data.databricks.governance.common
import future.keywords.contains
import future.keywords.if
import future.keywords.in

rule_metadata := {
	"missing_cost_center": {
		"id": "CST-MSE-001",
		"category": "cost",
		"description": "Serving endpoints must carry a cost_center tag for chargeback. Databricks-provided foundation models are exempt.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
	"no_scale_to_zero": {
		"id": "CST-MSE-002",
		"category": "cost",
		"description": "Non-production endpoints should scale to zero. A development endpoint holding warm capacity around the clock is pure waste.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
	"open_to_all_users": {
		"id": "SEC-MSE-003",
		"category": "security",
		"description": "Serving endpoints must not grant query access to all users.",
		"severity": "HIGH",
		"requested_action": "WARN",
		"destructive": false,
	},
	"no_inference_logging": {
		"id": "CTL-MSE-004",
		"category": "control",
		"description": "Production endpoints should log inference to a Unity Catalog table so behaviour can be audited after the fact.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
}

default applies := false

applies if {
	input.resource.type == "model_serving_endpoint"
}

# Databricks ships these; they carry no customer configuration to correct.
is_databricks_provided if {
	startswith(object.get(input.resource, "id", ""), "databricks-")
}

is_databricks_provided if {
	startswith(object.get(input.resource, "id", ""), "system-")
}

violations.missing_cost_center contains msg if {
	applies
	not is_databricks_provided
	not common.is_set(object.get(input.resource.tags, "cost_center", null))
	msg := "No 'cost_center' tag, so inference spend cannot be charged back."
}

violations.no_scale_to_zero contains msg if {
	applies
	not is_databricks_provided
	input.workspace.environment != "prod"
	object.get(input.resource, "scale_to_zero", true) == false
	msg := "Scale-to-zero is disabled outside production, so this endpoint bills continuously."
}

violations.open_to_all_users contains msg if {
	applies
	"ALL_USERS" in object.get(input.resource, "shared_with", [])
	msg := "Endpoint grants query access to all users."
}

violations.no_inference_logging contains msg if {
	applies
	not is_databricks_provided
	input.workspace.environment == "prod"
	object.get(input.resource, "inference_logging", false) == false
	msg := "Inference logging is disabled on a production endpoint."
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
