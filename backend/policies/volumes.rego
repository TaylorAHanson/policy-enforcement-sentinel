# METADATA
# title: Volume and storage governance
# description: |
#   Rules for Unity Catalog volumes and storage locations: where production data
#   is allowed to live and who can reach it.
#
#   This file never proposes anything that touches data. The volume handler
#   implements QUARANTINE, which strips grants and leaves every byte in place,
#   and DELETE exists only for empty volumes behind all five gates. Deleting
#   data is out of scope for automated governance, permanently.
# authors:
# - data-governance@company.com
# custom:
#   owner: data-governance
#   domain: data
#   resource_type: storage
package databricks.governance.volumes

import data.databricks.governance.common
import future.keywords.contains
import future.keywords.if
import future.keywords.in

rule_metadata := {
	"prod_data_in_dbfs": {
		"id": "SEC-VOL-001",
		"category": "security",
		"description": "Production data must not sit in DBFS or local volumes. Neither supports Unity Catalog access control or lineage.",
		"severity": "HIGH",
		"requested_action": "WARN",
		"destructive": false,
	},
	"granted_to_all_users": {
		"id": "SEC-VOL-002",
		"category": "security",
		"description": "Volumes must not grant access to all account users.",
		"severity": "HIGH",
		"requested_action": "WARN",
		"destructive": false,
	},
	"missing_classification": {
		"id": "CTL-VOL-003",
		"category": "control",
		"description": "Volumes must carry a data classification tag so downstream controls know what they are handling.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
	"no_owner": {
		"id": "CTL-VOL-004",
		"category": "control",
		"description": "Volumes must have an identifiable owner.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
}

default applies := false

applies if {
	input.resource.type == "storage"
}

violations.prod_data_in_dbfs contains msg if {
	applies
	object.get(input.resource, "storage_type", "") in {"dbfs", "local_volume"}
	input.workspace.environment == "prod"
	msg := "Production data is stored outside Unity Catalog, where access cannot be governed or traced."
}

violations.granted_to_all_users contains msg if {
	applies
	"account users" in object.get(input.resource, "principals", [])
	msg := "Volume grants access to 'account users', which is everyone."
}

violations.missing_classification contains msg if {
	applies
	not input.resource.tags.data_classification
	msg := "No data classification tag, so it is unknown whether this volume holds sensitive data."
}

violations.no_owner contains msg if {
	applies
	common.no_owner(input.resource)
	msg := "No owner recorded for this volume."
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
