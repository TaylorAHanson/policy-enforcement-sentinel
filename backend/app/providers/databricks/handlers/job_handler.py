import asyncio
import logging
from typing import Any, Dict, List

from app.providers.databricks import activity, destructive, identity, permissions
from app.providers.databricks.handlers.base import (
    BaseResourceHandler,
    SupportsDelete,
    SupportsDisable,
    SupportsRevokeAccess,
)

logger = logging.getLogger(__name__)


class JobResourceHandler(
    BaseResourceHandler, SupportsDisable, SupportsRevokeAccess, SupportsDelete
):
    """Workflow jobs.

    Pausing the schedule stops a non-compliant job from running again while
    leaving its definition and history intact, which is almost always what was
    actually wanted.
    """

    resource_type = "job"

    discovered_fields = {
        "id": "The job ID, as a string.",
        "name": "The job name, or null.",
        "type": 'Always "job".',
        "owner": "The email of whoever created the job.",
        "schedule": "The Quartz cron expression, or null when the job has no schedule.",
        "paused": "Whether the schedule is paused. False when there is no schedule at all.",
        "max_concurrent_runs": "Concurrency limit, or null.",
        "owner_type": (
            '"user", "service_principal", or "unknown" when the API named '
            "neither. Describes who the job runs as, not who created it — a job "
            "created by a person and running as a service principal is fine."
        ),
        "idle_days": (
            "Days since the job last ran. Absent for a job that has never run, "
            "which is not the same as an idle one, and absent when the run "
            "history could not be read."
        ),
        "failed_consecutively_days": (
            "How long the current unbroken run of failures has lasted. Absent "
            "unless the most recent finished run failed, so a job that failed "
            "for a month and was fixed reports nothing."
        ),
        "tags": "Job tags as a string map.",
    }

    async def discover(self) -> List[Dict[str, Any]]:
        jobs = list(self.workspace_client.jobs.list(expand_tasks=False))

        # Run history is a second call per job, so it happens once for the whole
        # set with bounded concurrency rather than inline in the loop.
        history = await activity.job_run_history(
            self.workspace_client, [job.job_id for job in jobs]
        )

        resources = []
        for job in jobs:
            settings_obj = getattr(job, "settings", None)
            schedule = getattr(settings_obj, "schedule", None) if settings_obj else None
            resource = {
                "id": str(job.job_id),
                "name": getattr(settings_obj, "name", None) if settings_obj else None,
                "type": "job",
                "owner": getattr(job, "creator_user_name", "unknown"),
                "schedule": getattr(schedule, "quartz_cron_expression", None)
                if schedule
                else None,
                "paused": (
                    str(getattr(schedule, "pause_status", "")).upper().endswith("PAUSED")
                    if schedule
                    else False
                ),
                "max_concurrent_runs": getattr(settings_obj, "max_concurrent_runs", None)
                if settings_obj
                else None,
                "owner_type": identity.owner_type(
                    getattr(settings_obj, "run_as", None) if settings_obj else None,
                    getattr(job, "creator_user_name", None),
                ),
                "tags": dict(getattr(settings_obj, "tags", None) or {})
                if settings_obj
                else {},
            }
            resources.append(
                activity.merge_known(resource, history.get(str(job.job_id), {}))
            )
        return resources

    # --- Tier 2 -----------------------------------------------------------

    async def disable(self, resource_id: str, *, authorization=None) -> Dict[str, Any]:
        from databricks.sdk.service import jobs as jobs_service

        current = await asyncio.to_thread(
            self.workspace_client.jobs.get, job_id=int(resource_id)
        )
        schedule = getattr(current.settings, "schedule", None)
        if schedule is None:
            raise ValueError(f"Job {resource_id} has no schedule to pause")

        undo_payload = {
            "resource_id": resource_id,
            "pause_status": str(getattr(schedule, "pause_status", "UNPAUSED")),
        }

        schedule.pause_status = jobs_service.PauseStatus.PAUSED
        await asyncio.to_thread(
            self.workspace_client.jobs.update,
            job_id=int(resource_id),
            new_settings=jobs_service.JobSettings(schedule=schedule),
        )
        logger.info("Paused schedule for job %s.", resource_id)
        return undo_payload

    async def enable(self, resource_id: str, undo_payload: Dict[str, Any]) -> bool:
        from databricks.sdk.service import jobs as jobs_service

        current = await asyncio.to_thread(
            self.workspace_client.jobs.get, job_id=int(resource_id)
        )
        schedule = getattr(current.settings, "schedule", None)
        if schedule is None:
            return False

        prior = undo_payload.get("pause_status", "UNPAUSED")
        schedule.pause_status = (
            jobs_service.PauseStatus.PAUSED
            if "PAUSED" in str(prior).upper() and "UNPAUSED" not in str(prior).upper()
            else jobs_service.PauseStatus.UNPAUSED
        )
        await asyncio.to_thread(
            self.workspace_client.jobs.update,
            job_id=int(resource_id),
            new_settings=jobs_service.JobSettings(schedule=schedule),
        )
        return True

    async def revoke_access(self, resource_id: str, *, authorization=None) -> Dict[str, Any]:
        return await asyncio.to_thread(
            permissions.revoke_permissions, self.workspace_client, "job", resource_id
        )

    async def restore_access(self, resource_id: str, undo_payload: Dict[str, Any]) -> bool:
        return await asyncio.to_thread(
            permissions.restore_permissions, self.workspace_client, undo_payload
        )

    # --- Tier 3 -----------------------------------------------------------

    async def delete(self, resource_id: str, *, authorization) -> bool:
        return await asyncio.to_thread(
            destructive.delete_job,
            self.workspace_client,
            resource_id,
            authorization=authorization,
        )
