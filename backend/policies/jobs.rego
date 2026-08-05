# METADATA
# title: Job governance
# description: |
#   Rules for scheduled and triggered jobs: ownership, cost attribution, and
#   jobs that have stopped earning their schedule.
#
#   Failing and abandoned jobs are the most tempting thing in the platform to
#   delete automatically, and the most consequential to get wrong -- a job that
#   has failed for a month may still be the only definition of a pipeline
#   somebody is mid-way through fixing. These rules warn. DISABLE (pausing the
#   schedule, fully reversible) is implemented if an operator wants to escalate.
# authors:
# - data-platform@company.com
# custom:
#   owner: data-platform
#   domain: compute
#   resource_type: job
package databricks.governance.jobs

import data.databricks.governance.common
import future.keywords.contains
import future.keywords.if
import future.keywords.in

rule_metadata := {
	"human_owner_in_prod": {
		"id": "SEC-JOB-001",
		"category": "security",
		"description": "Production jobs must run as a service principal. A job owned by a person breaks the day they change teams.",
		"severity": "HIGH",
		"requested_action": "WARN",
		"destructive": false,
	},
	"failing_consecutively": {
		"id": "CTL-JOB-002",
		"category": "reliability",
		"description": "A job that has failed on every run for weeks is either unowned or broken. Either way somebody should look at it.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
		"escalate_after_days": 30,
	},
	"idle": {
		"id": "CST-JOB-003",
		"category": "cost",
		"description": "Jobs that have not run in a long time should be retired so the schedule reflects reality.",
		"severity": "LOW",
		"requested_action": "WARN",
		"destructive": false,
		"escalate_after_days": 90,
	},
	"missing_cost_tags": {
		"id": "CST-JOB-004",
		"category": "cost",
		"description": "Jobs must carry cost-center and owner tags.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
	"no_failure_notification": {
		"id": "CTL-JOB-005",
		"category": "reliability",
		"description": "Production jobs must notify somebody on failure. A silent failure is indistinguishable from success until it matters.",
		"severity": "MEDIUM",
		"requested_action": "WARN",
		"destructive": false,
	},
}

default applies := false

applies if {
	input.resource.type == "job"
}

violations.human_owner_in_prod contains msg if {
	applies
	input.resource.owner_type == "user"
	input.workspace.environment == "prod"
	msg := "Production job runs as a human user. Move it to a service principal so it survives staff changes."
}

violations.failing_consecutively contains msg if {
	applies
	days := object.get(input.resource, "failed_consecutively_days", 0)
	days > 30
	msg := sprintf("Every run has failed for %v days.", [days])
}

violations.idle contains msg if {
	applies
	idle := object.get(input.resource, "idle_days", 0)
	idle > 90
	msg := sprintf("Has not run in %v days.", [idle])
}

violations.missing_cost_tags contains msg if {
	applies
	not input.resource.tags["cost-center"]
	msg := "Missing the 'cost-center' tag, so this job's spend cannot be attributed."
}

violations.missing_cost_tags contains msg if {
	applies
	not input.resource.tags.owner
	msg := "Missing the 'owner' tag, so there is nobody to notify about this job."
}

violations.no_failure_notification contains msg if {
	applies
	input.workspace.environment == "prod"
	count(object.get(input.resource, "failure_notification_targets", [])) == 0
	msg := "No failure notifications configured. Failures will go unnoticed."
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
