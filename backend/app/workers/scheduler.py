import asyncio
import logging
from datetime import datetime, timezone
from croniter import croniter
from app.core.config import settings
from app.services.sentinel_service import SentinelService
import uuid

logger = logging.getLogger(__name__)

async def start_scheduler():
    """
    Background worker that runs the Sentinel Service on a cron schedule
    defined by SENTINEL_CRON_SCHEDULE in the configuration.
    """
    schedule = settings.SENTINEL_CRON_SCHEDULE
    if not schedule:
        logger.info("Scheduled runs disabled (SENTINEL_CRON_SCHEDULE is not set).")
        return

    logger.info(f"Starting background scheduler with cron: '{schedule}'")
    
    try:
        cron = croniter(schedule, datetime.now(timezone.utc))
        next_run = cron.get_next(datetime)
        logger.info(f"Next scheduled sentinel run: {next_run}")
        
        while True:
            now = datetime.now(timezone.utc)
            if now >= next_run:
                run_id = str(uuid.uuid4())
                logger.info(f"Executing scheduled sentinel run (ID: {run_id})...")
                try:
                    # Execute the actual sentinel run
                    all_violations = []
                    total_scanned = 0
                    workspaces = settings.get_workspaces()
                    
                    for ws_conf in workspaces:
                        svc = SentinelService(workspace_config=ws_conf)
                        ws_name = ws_conf.get("name", "unknown")
                        ws_env = ws_conf.get("environment", "prod")
                        
                        results = await svc.run_discovery_and_evaluation(
                            workspace_name=ws_name,
                            environment=ws_env,
                            mode=settings.SENTINEL_CRON_MODE
                        )
                        total_scanned += results.get("total_scanned", 0)
                        all_violations.extend(results.get("violations", []))
                    
                    final_results = {
                        "total_scanned": total_scanned,
                        "total_violations": len(all_violations),
                        "violations": all_violations
                    }
                    
                    # Import and store the run in the in-memory history 
                    # (or database, if you upgrade to SQLite run history later)
                    from app.api.v1.endpoints.sentinel import run_history
                    
                    names = [w.get("name", "unknown") for w in workspaces]
                    
                    run_record = {
                        "id": run_id,
                        "workspace": ", ".join(names),
                        "environment": "multiple" if len(names) > 1 else workspaces[0].get("environment", "prod"),
                        "mode": settings.SENTINEL_CRON_MODE,
                        "status": "completed",
                        "started_at": now.isoformat(),
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "results": final_results
                    }
                    run_history.insert(0, run_record)
                    logger.info(f"Scheduled sentinel run (ID: {run_id}) completed successfully.")
                    
                except Exception as e:
                    logger.error(f"Scheduled sentinel run (ID: {run_id}) failed: {e}", exc_info=True)
                    
                    from app.api.v1.endpoints.sentinel import run_history
                    workspaces = settings.get_workspaces()
                    names = [w.get("name", "unknown") for w in workspaces]
                    run_record = {
                        "id": run_id,
                        "workspace": ", ".join(names),
                        "environment": "multiple" if len(names) > 1 else workspaces[0].get("environment", "prod"),
                        "mode": settings.SENTINEL_CRON_MODE,
                        "status": "failed",
                        "started_at": now.isoformat(),
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "error": str(e),
                        "results": None
                    }
                    run_history.insert(0, run_record)
                    
                finally:
                    next_run = cron.get_next(datetime)
                    logger.info(f"Next scheduled sentinel run: {next_run}")
            
            # Sleep briefly before checking the time again
            await asyncio.sleep(30)
            
    except Exception as e:
        logger.error(f"Scheduler worker crashed: {e}", exc_info=True)