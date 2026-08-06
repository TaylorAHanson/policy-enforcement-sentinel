# METADATA
# title: Dataset governance and certification
# description: |
#   Rules for Unity Catalog tables and views. Covers the certification
#   checklist -- metadata, ownership, classification, access control, data
#   quality -- and the sharing patterns that leak data.
#
#   Nothing in this file proposes deleting or modifying data, and nothing ever
#   should. The dataset handler implements exactly two verbs: certification
#   tagging and QUARANTINE, which removes grants and leaves the table untouched.
#
#   Certification is reported rather than applied. `certification` below states
#   whether the dataset currently meets the bar and what would change, and
#   granting or removing the badge stays an explicit operator action -- a scan
#   that silently uncertifies a table the moment a description goes missing
#   teaches people to distrust the badge.
# authors:
# - data-governance@company.com
# custom:
#   owner: data-governance
#   domain: data
#   resource_type: dataset
package databricks.governance.datasets

import data.databricks.governance.common
import future.keywords.contains
import future.keywords.if
import future.keywords.in

rule_metadata := {
	"missing_description": {
		"id": "CTL-DST-001",
		"category": "control",
		"description": "Tables and views must have a description. An undocumented table gets reinvented rather than reused.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
	"missing_column_descriptions": {
		"id": "CTL-DST-002",
		"category": "control",
		"description": "Every column must be documented.",
		"severity": "LOW",
		"requested_action": "WARN",
		"destructive": false,
	},
	"missing_required_tags": {
		"id": "CTL-DST-003",
		"category": "control",
		"description": "Datasets must carry the governance tag set: owner_group, approver_group, domain, and slo_sla.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
	"missing_classification": {
		"id": "SEC-DST-004",
		"category": "security",
		"description": "Datasets must declare a data classification so PII handling can be enforced downstream.",
		"severity": "HIGH",
		"requested_action": "WARN",
		"destructive": false,
	},
	"granted_to_all_users": {
		"id": "SEC-DST-005",
		"category": "security",
		"description": "Datasets must not be granted to all account users. Access is granted to groups whose membership somebody owns.",
		"severity": "HIGH",
		"requested_action": "WARN",
		"destructive": false,
	},
	"granted_to_individuals": {
		"id": "SEC-DST-006",
		"category": "security",
		"description": "Production grants must go to groups, not individuals. Individual grants survive role changes and offboarding.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
	"no_owner": {
		"id": "CTL-DST-007",
		"category": "control",
		"description": "Datasets must have an identifiable owner.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
	"failing_quality_rules": {
		"id": "CTL-DST-008",
		"category": "reliability",
		"description": "Datasets must have no failing data quality rules inside their declared reliability window.",
		"severity": "HIGH",
		"requested_action": "WARN",
		"destructive": false,
	},
	"missing_reliability_window": {
		"id": "CTL-DST-009",
		"category": "reliability",
		"description": "Datasets must declare a reliability_window tag stating how far back quality results are meaningful.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
	"stale": {
		"id": "CTL-DST-010",
		"category": "reliability",
		"description": "Tables that have not been written to in a long time may be abandoned upstream while still being read downstream.",
		"severity": "LOW",
		"requested_action": "WARN",
		"destructive": false,
		"escalate_after_days": 90,
	},
}

required_tags := {"owner_group", "approver_group", "domain", "slo_sla"}

#: Rules that must all pass before a dataset can carry the certified badge.
certification_rules := {
	"missing_description",
	"missing_column_descriptions",
	"missing_required_tags",
	"missing_classification",
	"no_owner",
	"failing_quality_rules",
	"missing_reliability_window",
}

default applies := false

applies if {
	input.resource.type == "dataset"
}

violations.missing_description contains msg if {
	applies
	object.get(input.resource, "comment", "") == ""
	msg := "No table or view description."
}

violations.missing_column_descriptions contains msg if {
	applies
	object.get(input.resource, "all_columns_have_descriptions", true) == false
	msg := "One or more columns have no description."
}

violations.missing_required_tags contains msg if {
	applies
	some tag in required_tags
	not input.resource.tags[tag]
	msg := sprintf("Required governance tag '%v' is missing.", [tag])
}

violations.missing_classification contains msg if {
	applies
	not input.resource.tags.data_classification
	msg := "No 'data_classification' tag, so it is unknown whether this dataset holds PII."
}

violations.granted_to_all_users contains msg if {
	applies
	"account users" in object.get(input.resource, "principals", [])
	msg := "Granted to 'account users', which is everyone in the account."
}

violations.granted_to_individuals contains msg if {
	applies
	input.workspace.environment == "prod"
	some grant in object.get(input.resource, "grants", [])
	grant.principal_type == "user"
	msg := sprintf("Production grant issued directly to the user '%v' rather than a group.", [grant.principal])
}

violations.no_owner contains msg if {
	applies
	common.no_owner(input.resource)
	msg := "No owner recorded for this dataset."
}

violations.missing_reliability_window contains msg if {
	applies
	not input.resource.tags.reliability_window
	msg := "No 'reliability_window' tag, so data quality results cannot be scoped to a period."
}

violations.failing_quality_rules contains msg if {
	applies
	input.resource.tags.reliability_window
	failed := object.get(input.resource, "failed_rule_count", 0)
	failed > 0
	msg := sprintf("%v data quality rules are failing inside the reliability window.", [failed])
}

# A negative count means the quality history could not be read. That is not the
# same as passing, and it must not be reported as such.
violations.failing_quality_rules contains msg if {
	applies
	input.resource.tags.reliability_window
	object.get(input.resource, "failed_rule_count", 0) < 0
	msg := "Could not read data quality history for the reliability window; treating the result as unknown rather than clean."
}

violations.stale contains msg if {
	applies
	idle := object.get(input.resource, "idle_days", 0)
	idle > 90
	msg := sprintf("No writes in %v days.", [idle])
}

default rule_results := []

rule_results := common.results(rule_metadata, violations) if {
	applies
}

# --- Certification ----------------------------------------------------------

failed_certification_rules := [rule_id |
	some rule_id in certification_rules
	count(object.get(violations, rule_id, set())) > 0
]

currently_certified if {
	object.get(input.resource, "tags", {})["system.certification_status"] == "certified"
}

default certification := {
	"applies": false,
	"eligible": false,
	"currently_certified": false,
	"failed_rules": [],
	"recommendation": "NONE",
}

certification := {
	"applies": true,
	"eligible": eligible,
	"currently_certified": certified,
	"failed_rules": sort(failed_certification_rules),
	"recommendation": recommendation,
} if {
	applies
	eligible := count(failed_certification_rules) == 0
	certified := currently_certified
	recommendation := certification_recommendation(eligible, certified)
}

certification_recommendation(eligible, certified) := "CERTIFY" if {
	eligible
	not certified
}

certification_recommendation(eligible, certified) := "REVIEW_FOR_UNCERTIFY" if {
	not eligible
	certified
}

certification_recommendation(eligible, certified) := "KEEP_CERTIFIED" if {
	eligible
	certified
}

certification_recommendation(eligible, certified) := "KEEP_UNCERTIFIED" if {
	not eligible
	not certified
}

summary := common.summarize(rule_metadata, violations) if {
	applies
} else := common.not_applicable

action := summary.action

is_violation := summary.is_violation

reason := summary.reason

severity := summary.severity
