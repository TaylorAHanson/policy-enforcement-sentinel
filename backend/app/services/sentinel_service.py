"""The scan engine.

Discovers resources across one or more workspaces, evaluates each against the
Rego policies, records every verdict, and — only through the chokepoint —
remediates.

Design notes worth knowing before changing anything here:

* **One OPA call per resource.** ``evaluate_namespace`` returns every policy's
  verdict at once. The previous shape was one subprocess spawn per resource per
  policy, which on a few thousand resources is tens of thousands of forks.

* **Failure is not silence.** A workspace whose auth probe fails records a
  ``ws_failure`` finding and marks the run partial. Without that, a scan that
  couldn't authenticate reports zero violations, which reads exactly like a
  clean estate.

* **Passes are recorded too.** Knowing a resource was checked and complied is
  different from it never having been evaluated.

* **Sessions are short-lived.** The database connection is taken, used, and
  released around each of the three touch points. Holding one across a
  multi-minute scan is how an idle-timeout drop takes the whole run with it.

* **Every remediation goes through ``resolve_effective_action``.** There is no
  branch in this file that decides for itself what an action means.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from app.core.actions import ActionTier, normalize_action
from app.core.config import settings
from app.core.enforcement import (
    ActionRequest,
    EffectiveAction,
    EnforcementApproval,
    ScanMode,
    resolve_effective_action,
)
from app.db.allowlist import AllowlistModel
from app.db.sentinel_finding import SentinelFindingModel
from app.providers.databricks.client import DatabricksProvider
from app.providers.databricks.handlers import HANDLER_REGISTRY, supported_methods
from app.providers.opa.client import OpaProvider
from app.services.action_executor import execute_action

logger = logging.getLogger(__name__)

# Blocking SDK calls run here rather than on the default asyncio executor, so a
# slow workspace can't starve every other `to_thread` in the process.
_scan_executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix="sentinel-scan")

FINDING_BATCH_SIZE = 500


async def _gather_bounded(coros: Sequence, limit: int) -> List[Any]:
    """Run coroutines with at most ``limit`` in flight.

    ``asyncio.gather`` over every resource at once opens more connections than
    the SDK's pool allows and trips workspace rate limits; a fixed semaphore
    sized for one estate is wrong for the next one. This is the tunable version.
    """
    semaphore = asyncio.Semaphore(max(1, limit))

    async def _run(coro):
        async with semaphore:
            return await coro

    return await asyncio.gather(*[_run(c) for c in coros], return_exceptions=True)


class SentinelService:
    def __init__(self, workspace_config: Optional[Dict[str, str]] = None):
        self.opa_provider = OpaProvider(settings.opa_provider_config())
        self.workspace_config = workspace_config or {}

        config = self.workspace_config
        self.db_provider = DatabricksProvider(
            host=config.get("host")
            or settings.DATABRICKS_HOST
            or settings.DATABRICKS_WORKSPACE_URL
            or "",
            client_id=config.get("client_id") or settings.DATABRICKS_CLIENT_ID,
            client_secret=config.get("client_secret") or settings.DATABRICKS_CLIENT_SECRET,
            token=config.get("token") or settings.DATABRICKS_TOKEN,
        )

    # --- Allowlist --------------------------------------------------------

    @staticmethod
    def _load_allowlist(workspace_name: str) -> List[Dict[str, Any]]:
        """Read the allowlist for a workspace, in one short-lived session.

        **All** statuses are loaded, not just approved. A pending exception has
        to reach Rego for it to resolve to ``PENDING_EXCEPTION`` and hold the
        violation rather than acting on a resource whose waiver is mid-review.
        """
        from app.db.session import get_lakebase_session

        db = get_lakebase_session()
        try:
            rows = (
                db.query(AllowlistModel)
                .filter(AllowlistModel.workspace == workspace_name)
                .all()
            )
            records = []
            for row in rows:
                expires_at = getattr(row, "expires_at", None)
                records.append(
                    {
                        "id": row.id,
                        "resource_id": row.resource_id,
                        "resource_type": row.resource_type,
                        "status": row.status,
                        "justification": row.justification,
                        # Defaulted rather than passed through as null. A row
                        # written before patterns existed waives one named
                        # resource, and the one thing that must not happen is
                        # for its absence of a match_type to be read as
                        # anything broader.
                        "match_type": getattr(row, "match_type", None) or "resource",
                        "rule_id": getattr(row, "rule_id", None) or "",
                        # ISO string or JSON null. Rego's `not exception.expires_at`
                        # never matches a JSON null, so common.rego tests for it
                        # explicitly with object.get(..., null).
                        "expires_at": expires_at.isoformat() if expires_at else None,
                    }
                )
            return records
        except Exception as e:
            logger.error("Could not load the allowlist for %s: %s", workspace_name, e)
            return []
        finally:
            db.close()

    # --- Discovery --------------------------------------------------------

    async def _discover_all(self, workspace_client, workspace_name: str):
        """Discover every resource type. Returns (resources, discovery_errors)."""
        handlers = {
            resource_type: handler_class(workspace_client)
            for resource_type, handler_class in HANDLER_REGISTRY.items()
        }

        async def _discover(resource_type: str, handler):
            try:
                return resource_type, await handler.discover(), None
            except Exception as e:
                # Handlers re-raise so this can classify the failure. A type we
                # could not enumerate is reported, never treated as empty.
                logger.error(
                    "Discovery failed for %s in %s: %s: %s",
                    resource_type,
                    workspace_name,
                    type(e).__name__,
                    e,
                )
                return resource_type, [], f"{type(e).__name__}: {e}"

        results = await _gather_bounded(
            [_discover(rt, h) for rt, h in handlers.items()],
            settings.SENTINEL_SCAN_CONCURRENCY,
        )

        resources: List[Dict[str, Any]] = []
        errors: Dict[str, str] = {}
        for result in results:
            if isinstance(result, Exception):
                logger.error("Discovery task raised: %s", result)
                continue
            resource_type, discovered, error = result
            if error:
                errors[resource_type] = error
            for resource in discovered or []:
                resource.setdefault("type", resource_type)
                resources.append(resource)

        return resources, errors, handlers

    async def _probe_auth(self, workspace_client, workspace_name: str) -> Optional[str]:
        """Confirm we can actually talk to the workspace before believing a scan.

        Returns an error string on failure. Discovery handlers return empty
        lists for a workspace we cannot authenticate to, which is
        indistinguishable from a compliant one — this is what makes the
        difference visible.
        """
        try:
            loop = asyncio.get_running_loop()
            me = await loop.run_in_executor(_scan_executor, workspace_client.current_user.me)
            logger.info("Authenticated to %s as %s", workspace_name, getattr(me, "user_name", "?"))
            return None
        except Exception as e:
            return f"{type(e).__name__}: {e}"

    # --- Evaluation -------------------------------------------------------

    async def _evaluate_resource(
        self,
        resource: Dict[str, Any],
        *,
        workspace_name: str,
        workspace_type: str,
        environment: str,
        allowlist_records: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Evaluate one resource against every policy. Returns raw findings."""
        input_data = {
            "workspace": {
                "name": workspace_name,
                "type": workspace_type,
                "environment": environment,
            },
            "resource": resource,
            "request_time": datetime.now(timezone.utc).isoformat(),
            "allowlist_records": allowlist_records,
        }

        try:
            results = await self.opa_provider.evaluate_namespace(input_data)
        except Exception as e:
            logger.error(
                "Policy evaluation failed for %s %s: %s: %s",
                resource.get("type"),
                resource.get("id"),
                type(e).__name__,
                e,
            )
            # An evaluation we could not complete is reported as a failure, not
            # as a pass and certainly not as an action.
            return [
                {
                    "kind": "ws_failure",
                    "policy": None,
                    "message": f"Policy evaluation failed: {type(e).__name__}: {e}",
                    "severity": "HIGH",
                    "resource": resource,
                }
            ]

        findings: List[Dict[str, Any]] = []
        for policy_name, result in results.items():
            findings.extend(self._findings_from_result(policy_name, result, resource))
        return findings

    @staticmethod
    def _findings_from_result(
        policy_name: str, result: Dict[str, Any], resource: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Turn one policy's output into finding dicts.

        Handles both the current shape (``rule_results`` with per-rule detail)
        and the older flat shape, so a policy mid-migration still produces
        something sensible.
        """
        findings: List[Dict[str, Any]] = []

        if not result.get("applies", True):
            return findings

        rule_results = result.get("rule_results")
        if isinstance(rule_results, list) and rule_results:
            for rule in rule_results:
                if not isinstance(rule, dict):
                    continue
                passed = bool(rule.get("passed"))
                findings.append(
                    {
                        "kind": "check" if passed else "violation",
                        "policy": policy_name,
                        "rule_id": rule.get("rule"),
                        "policy_id": rule.get("id"),
                        "category": rule.get("category"),
                        "severity": rule.get("severity") or result.get("severity") or "MEDIUM",
                        "message": "; ".join(rule.get("messages") or [])
                        or rule.get("description")
                        or "",
                        # Absent on a passing rule, and absent means WARN — the
                        # chokepoint decides, this only reports what was asked.
                        "requested_action": None
                        if passed
                        else (rule.get("requested_action") or result.get("requested_action")),
                        "destructive": bool(rule.get("destructive")),
                        "resource": resource,
                    }
                )
            return findings

        # Legacy shape: a single verdict for the whole policy.
        is_violation = bool(result.get("is_violation"))
        requested = result.get("requested_action", result.get("action"))
        if is_violation or normalize_action(requested) in ("CERTIFY", "UNCERTIFY"):
            findings.append(
                {
                    "kind": "violation",
                    "policy": policy_name,
                    "rule_id": None,
                    "policy_id": result.get("policy_id"),
                    "category": result.get("category"),
                    "severity": result.get("severity", "MEDIUM"),
                    "message": result.get("reason", "Policy violation"),
                    "requested_action": requested,
                    "destructive": bool(result.get("destructive")),
                    "resource": resource,
                }
            )
        elif result.get("applies"):
            findings.append(
                {
                    "kind": "check",
                    "policy": policy_name,
                    "rule_id": None,
                    "severity": None,
                    "message": "Compliant",
                    "requested_action": None,
                    "destructive": False,
                    "resource": resource,
                }
            )
        return findings

    # --- Remediation ------------------------------------------------------

    def _resolve(
        self,
        finding: Dict[str, Any],
        *,
        workspace_name: str,
        mode: ScanMode,
        run_id: str,
        handler,
        approval: Optional[EnforcementApproval],
        destructive_candidates: int,
    ) -> EffectiveAction:
        resource = finding.get("resource", {})
        return resolve_effective_action(
            ActionRequest(
                requested_action=finding.get("requested_action"),
                resource_type=resource.get("type", "unknown"),
                resource_id=str(resource.get("id", "")),
                workspace=workspace_name,
                mode=mode,
                run_id=run_id,
                policy_declares_destructive=bool(finding.get("destructive")),
                supported_methods=supported_methods(handler) if handler else None,
                approval=approval,
                destructive_candidate_count=destructive_candidates,
            )
        )

    # --- The scan ---------------------------------------------------------

    async def scan_workspace(
        self,
        workspace_name: str,
        environment: str,
        *,
        mode: ScanMode = ScanMode.AUDIT,
        run_id: Optional[str] = None,
        approval: Optional[EnforcementApproval] = None,
    ) -> Dict[str, Any]:
        """Scan one workspace end to end."""
        run_id = run_id or str(uuid.uuid4())
        started = datetime.utcnow()
        logger.info("Scanning %s (%s) in %s mode.", workspace_name, environment, mode.value)

        summary: Dict[str, Any] = {
            "workspace": workspace_name,
            "environment": environment,
            "status": "completed",
            "total_resources": 0,
            "violations": 0,
            "checks": 0,
            "remediated": 0,
            "downgraded": 0,
            "errors": {},
        }
        findings_rows: List[SentinelFindingModel] = []

        try:
            workspace_client = self.db_provider.client
        except Exception as e:
            summary["status"] = "failed"
            summary["errors"]["client"] = str(e)
            findings_rows.append(
                self._failure_row(run_id, workspace_name, environment, f"Client init failed: {e}")
            )
            self._persist_findings(findings_rows)
            return summary

        auth_error = await self._probe_auth(workspace_client, workspace_name)
        if auth_error:
            logger.error("Auth probe failed for %s: %s", workspace_name, auth_error)
            summary["status"] = "failed"
            summary["errors"]["auth"] = auth_error
            findings_rows.append(
                self._failure_row(
                    run_id,
                    workspace_name,
                    environment,
                    f"Authentication failed: {auth_error}. No conclusions can be drawn "
                    "about this workspace from this run.",
                )
            )
            self._persist_findings(findings_rows)
            return summary

        allowlist_records = self._load_allowlist(workspace_name)
        resources, discovery_errors, handlers = await self._discover_all(
            workspace_client, workspace_name
        )
        summary["errors"].update(discovery_errors)
        summary["total_resources"] = len(resources)
        if discovery_errors:
            summary["status"] = "partial"

        for resource_type, error in discovery_errors.items():
            findings_rows.append(
                self._failure_row(
                    run_id,
                    workspace_name,
                    environment,
                    f"Could not enumerate {resource_type}: {error}",
                    resource_type=resource_type,
                )
            )

        logger.info(
            "Discovered %d resource(s) in %s; evaluating.", len(resources), workspace_name
        )

        workspace_type = "enterprise" if "enterprise" in workspace_name else "domain"
        evaluation_results = await _gather_bounded(
            [
                self._evaluate_resource(
                    resource,
                    workspace_name=workspace_name,
                    workspace_type=workspace_type,
                    environment=environment,
                    allowlist_records=allowlist_records,
                )
                for resource in resources
            ],
            settings.SENTINEL_SCAN_CONCURRENCY,
        )

        all_findings: List[Dict[str, Any]] = []
        for result in evaluation_results:
            if isinstance(result, Exception):
                logger.error("Evaluation task raised: %s", result)
                summary["status"] = "partial"
                continue
            all_findings.extend(result)

        # The blast-radius gate is a property of the whole run, so it has to be
        # counted before any single action is resolved.
        destructive_candidates = sum(
            1
            for f in all_findings
            if f.get("destructive") and normalize_action(f.get("requested_action"))
        )
        if destructive_candidates:
            logger.warning(
                "%d finding(s) in %s request destructive action.",
                destructive_candidates,
                workspace_name,
            )

        for finding in all_findings:
            resource = finding.get("resource", {})
            handler = handlers.get(resource.get("type"))

            if finding["kind"] == "check":
                findings_rows.append(
                    self._finding_row(run_id, workspace_name, environment, finding, None)
                )
                summary["checks"] += 1
                continue

            if finding["kind"] == "ws_failure":
                findings_rows.append(
                    self._finding_row(run_id, workspace_name, environment, finding, None)
                )
                summary["status"] = "partial"
                continue

            effective = self._resolve(
                finding,
                workspace_name=workspace_name,
                mode=mode,
                run_id=run_id,
                handler=handler,
                approval=approval,
                destructive_candidates=destructive_candidates,
            )
            summary["violations"] += 1
            if effective.downgraded:
                summary["downgraded"] += 1

            executed = False
            if handler is not None and effective.has_side_effect:
                outcome = await execute_action(
                    handler,
                    effective,
                    workspace=workspace_name,
                    resource_id=str(resource.get("id", "")),
                    resource_type=resource.get("type", "unknown"),
                    message=finding.get("message", ""),
                    owner=resource.get("owner"),
                    run_id=run_id,
                    policy=finding.get("policy"),
                    policy_id=finding.get("policy_id"),
                    approved_by=approval.approved_by if approval else None,
                    approval_id=approval.approval_id if approval else None,
                )
                executed = bool(outcome.get("executed"))
                if executed:
                    summary["remediated"] += 1

            row = self._finding_row(run_id, workspace_name, environment, finding, effective)
            row.executed = executed
            findings_rows.append(row)

        self._persist_findings(findings_rows)

        summary["duration_seconds"] = (datetime.utcnow() - started).total_seconds()
        logger.info(
            "Scan of %s finished: %d resources, %d violations, %d remediated, %d downgraded.",
            workspace_name,
            summary["total_resources"],
            summary["violations"],
            summary["remediated"],
            summary["downgraded"],
        )
        return summary

    async def run_discovery_and_evaluation(
        self, workspace_name: str, environment: str, mode: str = "audit", run_id: str = None
    ) -> Dict[str, Any]:
        """Backwards-compatible single-workspace entry point."""
        summary = await self.scan_workspace(
            workspace_name,
            environment,
            mode=coerce_mode(mode),
            run_id=run_id,
        )
        return {
            "total_scanned": summary["total_resources"],
            "total_violations": summary["violations"],
            "summary": summary,
        }

    # --- Persistence ------------------------------------------------------

    @staticmethod
    def _finding_row(
        run_id: str,
        workspace: str,
        environment: str,
        finding: Dict[str, Any],
        effective: Optional[EffectiveAction],
    ) -> SentinelFindingModel:
        resource = finding.get("resource", {})
        row = SentinelFindingModel(
            run_id=run_id,
            kind=finding.get("kind", "violation"),
            workspace=workspace,
            environment=environment,
            resource_id=str(resource.get("id", "")) or None,
            resource_type=resource.get("type"),
            resource_name=resource.get("name"),
            owner=resource.get("owner"),
            policy=finding.get("policy"),
            rule_id=finding.get("rule_id"),
            policy_id=finding.get("policy_id"),
            category=finding.get("category"),
            severity=finding.get("severity"),
            message=finding.get("message"),
            data={
                "resource": resource,
                "rule": finding.get("rule_id"),
                "action": effective.to_dict() if effective else None,
            },
        )

        if effective is not None:
            row.requested_action = effective.requested_action
            row.effective_action = effective.action
            row.tier = int(effective.tier)
            row.requested_tier = int(effective.requested_tier)
            row.downgrade_reason = effective.downgrade_reason

        return row

    @staticmethod
    def _failure_row(
        run_id: str,
        workspace: str,
        environment: str,
        message: str,
        resource_type: Optional[str] = None,
    ) -> SentinelFindingModel:
        row = SentinelFindingModel(
            run_id=run_id,
            kind="ws_failure",
            workspace=workspace,
            environment=environment,
            resource_type=resource_type,
            severity="HIGH",
            message=message,
            data={"error": message},
        )
        return row

    @staticmethod
    def _persist_findings(rows: List[SentinelFindingModel]) -> None:
        """Write findings in batches, each in its own short-lived session."""
        if not rows:
            return

        from app.db.session import get_lakebase_session

        for start in range(0, len(rows), FINDING_BATCH_SIZE):
            batch = rows[start : start + FINDING_BATCH_SIZE]
            db = get_lakebase_session()
            try:
                db.add_all(batch)
                db.commit()
            except Exception as e:
                logger.error("Failed to persist a batch of findings: %s", e)
                db.rollback()
            finally:
                db.close()

    # --- Manual actions ---------------------------------------------------

    async def execute_manual_action(
        self,
        action: str,
        resource_type: str,
        resource_id: str,
        *,
        workspace: str,
        reason: str = "Manual execution",
        mode: ScanMode = ScanMode.REMEDIATE,
        approval: Optional[EnforcementApproval] = None,
        run_id: Optional[str] = None,
        requested_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Act on a single resource from the UI or an MCP tool.

        Goes through exactly the same chokepoint as a scheduled scan. A manual
        action is not a way around the gates.
        """
        handler_class = HANDLER_REGISTRY.get(resource_type)
        if handler_class is None:
            return {"success": False, "error": f"No handler for {resource_type}"}

        try:
            handler = handler_class(self.db_provider.client)
        except Exception as e:
            return {"success": False, "error": f"Could not initialise the client: {e}"}

        effective = resolve_effective_action(
            ActionRequest(
                requested_action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                workspace=workspace,
                mode=mode,
                run_id=run_id,
                # A manual action carries no rule metadata, so this gate can
                # never pass from here. Destructive actions belong to a policy
                # that declared them, not to a button.
                policy_declares_destructive=False,
                supported_methods=supported_methods(handler),
                approval=approval,
                destructive_candidate_count=1,
            )
        )

        outcome = await execute_action(
            handler,
            effective,
            workspace=workspace,
            resource_id=resource_id,
            resource_type=resource_type,
            message=reason,
            run_id=run_id,
            approved_by=requested_by,
        )

        return {
            "success": bool(outcome.get("executed")),
            "requested_action": effective.requested_action,
            "effective_action": effective.action,
            "tier": int(effective.tier),
            "downgraded": effective.downgraded,
            "downgrade_reason": effective.downgrade_reason,
            "audit_id": outcome.get("audit_id"),
            "error": outcome.get("error"),
        }

    # Retained under the old name so existing callers keep working.
    async def execute_action(
        self, action: str, resource_type: str, resource_id: str, reason: str = "Manual execution"
    ) -> Dict[str, Any]:
        return await self.execute_manual_action(
            action,
            resource_type,
            resource_id,
            workspace=self.workspace_config.get("name", ""),
            reason=reason,
        )


def coerce_mode(mode: Any) -> ScanMode:
    """Turn a mode string into a ``ScanMode``, defaulting to the safest one."""
    if isinstance(mode, ScanMode):
        return mode
    try:
        return ScanMode(str(mode).strip().lower())
    except ValueError:
        logger.warning("Unknown scan mode %r; falling back to audit.", mode)
        return ScanMode.AUDIT


def build_approval(
    run_id: str, approved_by: str, workspace: str, ttl_minutes: Optional[int] = None
) -> EnforcementApproval:
    """Create a run-scoped, expiring approval."""
    ttl = ttl_minutes or settings.ENFORCEMENT_APPROVAL_TTL_MINUTES
    return EnforcementApproval(
        run_id=run_id,
        approved_by=approved_by,
        workspace=workspace,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=ttl),
        approval_id=str(uuid.uuid4()),
    )


async def scan_workspaces(
    workspaces: Iterable[Dict[str, str]],
    *,
    mode: ScanMode = ScanMode.AUDIT,
    run_id: Optional[str] = None,
    approval: Optional[EnforcementApproval] = None,
) -> Dict[str, Any]:
    """Scan several workspaces concurrently.

    Concurrency lives here rather than in the API layer, which used to loop over
    workspaces serially — so a ten-workspace scan took ten times as long as it
    needed to.
    """
    run_id = run_id or str(uuid.uuid4())
    workspace_list = list(workspaces)

    def _failed(name: str, environment: str, errors: Dict[str, str]) -> Dict[str, Any]:
        return {
            "workspace": name,
            "environment": environment,
            "status": "failed",
            "errors": errors,
            "total_resources": 0,
            "violations": 0,
            "checks": 0,
            "remediated": 0,
            "downgraded": 0,
        }

    async def _one(config: Dict[str, str]) -> Dict[str, Any]:
        name = config.get("name", "unknown")
        environment = config.get("environment", "unknown")
        try:
            service = SentinelService(config)
            return await asyncio.wait_for(
                service.scan_workspace(
                    name,
                    environment,
                    mode=mode,
                    run_id=run_id,
                    approval=approval,
                ),
                timeout=settings.SENTINEL_WORKSPACE_SCAN_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.error(
                "Scan of %s exceeded %ss and was abandoned.",
                name,
                settings.SENTINEL_WORKSPACE_SCAN_TIMEOUT_SECONDS,
            )
            return _failed(name, environment, {"timeout": "Workspace scan timed out"})
        except Exception as e:
            # Named, so the UI can say *which* workspace nobody has results for.
            # A summary with no workspace attached is indistinguishable from one
            # that was never scheduled.
            logger.error("Scan of %s raised: %s: %s", name, type(e).__name__, e)
            return _failed(name, environment, {"exception": f"{type(e).__name__}: {e}"})

    results = await _gather_bounded(
        [_one(config) for config in workspace_list],
        settings.SENTINEL_WORKSPACE_CONCURRENCY,
    )

    workspace_summaries = []
    for result in results:
        if isinstance(result, Exception):
            logger.error("Workspace scan raised: %s", result)
            workspace_summaries.append({"status": "failed", "errors": {"exception": str(result)}})
        else:
            workspace_summaries.append(result)

    totals = {
        "total_resources": sum(s.get("total_resources", 0) for s in workspace_summaries),
        "violations": sum(s.get("violations", 0) for s in workspace_summaries),
        "checks": sum(s.get("checks", 0) for s in workspace_summaries),
        "remediated": sum(s.get("remediated", 0) for s in workspace_summaries),
        "downgraded": sum(s.get("downgraded", 0) for s in workspace_summaries),
    }

    statuses = {s.get("status", "failed") for s in workspace_summaries}
    if statuses == {"completed"}:
        overall = "completed"
    elif "completed" in statuses or "partial" in statuses:
        overall = "partial"
    else:
        overall = "failed"

    return {
        "run_id": run_id,
        "status": overall,
        "mode": mode.value,
        "workspaces": workspace_summaries,
        **totals,
    }
