import asyncio
import logging
from typing import Any, Dict, List, Set

from app.core.config import settings
from app.providers.databricks import destructive
from app.providers.databricks.handlers.base import BaseResourceHandler, SupportsDelete

logger = logging.getLogger(__name__)


class NotebookResourceHandler(BaseResourceHandler, SupportsDelete):
    """Workspace notebooks.

    Walking the workspace tree is expensive, so this is gated behind
    ``SENTINEL_SCAN_NOTEBOOKS`` and off by default.
    """

    resource_type = "notebook"

    discovered_fields = {
        "id": "The workspace path, which is the notebook's identifier.",
        "name": "The final path segment.",
        "type": 'Always "notebook".',
        "owner": "The owning user, inferred from the path for anything under /Users.",
        "path": "The workspace path. The same value as `id`, named as the rules ask for it.",
        "language": "PYTHON, SQL, SCALA, R. May be an empty string.",
        "in_shared": "Whether the path is under /Shared.",
        "in_git_folder": (
            "Whether the notebook lives under a Git folder. True for anything "
            "under /Repos, and for anything beneath a folder the workspace "
            "reports as a repo, since Git folders may now live anywhere."
        ),
        "is_scheduled": (
            "Whether a job task runs this notebook. Derived by reading every "
            "job's tasks once per scan, so it reflects jobs the scanner can "
            "see — a notebook scheduled by a job we cannot read reads as False."
        ),
        "tags": "Always empty. Workspace objects carry no tags.",
    }

    async def discover(self) -> List[Dict[str, Any]]:
        if not settings.SENTINEL_SCAN_NOTEBOOKS:
            logger.debug("Notebook scanning disabled (SENTINEL_SCAN_NOTEBOOKS is off).")
            return []

        from databricks.sdk.service import workspace as workspace_service

        scheduled = await self._scheduled_notebook_paths()

        resources: List[Dict[str, Any]] = []
        for base_path in ("/Users", "/Shared"):
            try:
                objects = await asyncio.to_thread(
                    lambda p=base_path: list(
                        self.workspace_client.workspace.list(path=p, recursive=True)
                    )
                )
            except Exception as e:
                # One inaccessible root shouldn't abandon the other.
                logger.warning("Could not list notebooks under %s: %s", base_path, e)
                continue

            # The recursive listing hands back the repo folders alongside the
            # notebooks inside them, so one pass collects the roots and the
            # next asks which notebooks sit beneath one.
            repo_roots = [
                obj.path
                for obj in objects
                if getattr(obj, "object_type", None) == workspace_service.ObjectType.REPO
                and getattr(obj, "path", None)
            ]

            for obj in objects:
                if getattr(obj, "object_type", None) != workspace_service.ObjectType.NOTEBOOK:
                    continue
                path = obj.path
                # /Users/<email>/... is the only reliable ownership signal the
                # workspace API gives us without a per-object ACL lookup.
                owner = "unknown"
                if path.startswith("/Users/"):
                    parts = path.split("/")
                    if len(parts) > 2:
                        owner = parts[2]

                resources.append(
                    {
                        "id": path,
                        "name": path.rsplit("/", 1)[-1],
                        "type": "notebook",
                        "owner": owner,
                        "path": path,
                        "language": str(getattr(obj, "language", "") or ""),
                        "in_shared": path.startswith("/Shared"),
                        "in_git_folder": self._in_git_folder(path, repo_roots),
                        "is_scheduled": path in scheduled,
                        "tags": {},
                    }
                )
        return resources

    @staticmethod
    def _in_git_folder(path: str, repo_roots: List[str]) -> bool:
        if path.startswith("/Repos/"):
            return True
        return any(path.startswith(root.rstrip("/") + "/") for root in repo_roots)

    async def _scheduled_notebook_paths(self) -> Set[str]:
        """Notebook paths that some job task runs.

        One listing for the whole scan rather than a lookup per notebook. If it
        fails, every notebook reads as unscheduled, which silences the two rules
        that depend on it rather than firing them on a guess — a notebook wrongly
        called unscheduled is quiet, one wrongly called scheduled is a false
        accusation about production.
        """
        paths: Set[str] = set()
        try:
            jobs = await asyncio.to_thread(
                lambda: list(self.workspace_client.jobs.list(expand_tasks=True))
            )
        except Exception as e:
            logger.warning("Could not read jobs to tell which notebooks are scheduled: %s", e)
            return paths

        for job in jobs:
            settings_obj = getattr(job, "settings", None)
            for task in getattr(settings_obj, "tasks", None) or []:
                notebook_task = getattr(task, "notebook_task", None)
                notebook_path = getattr(notebook_task, "notebook_path", None)
                if notebook_path:
                    paths.add(notebook_path)
        return paths

    async def delete(self, resource_id: str, *, authorization) -> bool:
        return await asyncio.to_thread(
            destructive.delete_notebook,
            self.workspace_client,
            resource_id,
            authorization=authorization,
        )
