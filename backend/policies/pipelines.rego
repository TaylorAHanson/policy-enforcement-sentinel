# METADATA
# title: Declarative pipeline governance
# description: |
#   Rules for Spark declarative pipelines: compute mode, expectations, target
#   catalogs, and ownership.
#
#   The pipeline handler implements DISABLE by switching a continuous pipeline
#   to triggered, which pauses spend without discarding state and can be undone.
#   That is the only escalation this file should ever grow.
# authors:
# - data-platform@company.com
# custom:
#   owner: data-platform
#   domain: pipelines
#   resource_type: pipeline
package databricks.governance.pipelines

import data.databricks.governance.common
import future.keywords.contains
import future.keywords.if
import future.keywords.in

rule_metadata := {
	"not_serverless": {
		"id": "CST-PIP-001",
		"category": "cost",
		"description": "Pipelines should use serverless compute, which starts faster and stops paying when idle.",
		"severity": "LOW",
		"requested_action": "WARN",
		"destructive": false,
	},
	"no_expectations": {
		"id": "CTL-PIP-002",
		"category": "reliability",
		"description": "Production pipelines must declare data quality expectations. A pipeline with no expectations publishes bad data as confidently as good.",
		"severity": "HIGH",
		"requested_action": "WARN",
		"destructive": false,
	},
	"hive_metastore_target": {
		"id": "CTL-PIP-003",
		"category": "control",
		"description": "Pipelines must publish to Unity Catalog rather than the legacy Hive metastore.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
	"human_owner_in_prod": {
		"id": "SEC-PIP-004",
		"category": "security",
		"description": "Production pipelines must run as a service principal.",
		"severity": "HIGH",
		"requested_action": "WARN",
		"destructive": false,
	},
	"continuous_in_dev": {
		"id": "CST-PIP-005",
		"category": "cost",
		"description": "Continuous mode outside production keeps compute alive indefinitely. Triggered runs are almost always what was meant.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
}

default applies := false

applies if {
	input.resource.type == "pipeline"
}

violations.not_serverless contains msg if {
	applies
	object.get(input.resource.attributes, "serverless", true) == false
	msg := "Pipeline uses classic compute rather than serverless."
}

violations.no_expectations contains msg if {
	applies
	input.workspace.environment == "prod"
	object.get(input.resource.attributes, "expectation_count", 0) == 0
	msg := "Production pipeline declares no data quality expectations."
}

violations.hive_metastore_target contains msg if {
	applies
	object.get(input.resource.attributes, "target_catalog", "") == "hive_metastore"
	msg := "Pipeline publishes to hive_metastore, which has no Unity Catalog governance or lineage."
}

violations.human_owner_in_prod contains msg if {
	applies
	input.workspace.environment == "prod"
	object.get(input.resource, "owner_type", "") == "user"
	msg := "Production pipeline runs as a human user rather than a service principal."
}

violations.continuous_in_dev contains msg if {
	applies
	input.workspace.environment != "prod"
	object.get(input.resource.attributes, "continuous", false) == true
	msg := "Continuous mode outside production keeps compute running indefinitely."
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
