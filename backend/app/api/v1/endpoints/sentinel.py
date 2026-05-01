from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Dict, Any, List
import uuid
import datetime
from app.services.sentinel_service import SentinelService

router = APIRouter()

# In-memory run store for simplicity since we stripped the database tables
# You can upgrade this to SQLite if needed
run_history = []

class EnforcementActionRequest(BaseModel):
    resource_id: str
    resource_type: str
    action: str
    policy_name: str
    reason: str = "Manual execution via UI"
    workspace: str = None

@router.post("/runs/{run_id}/enforcement-action")
async def execute_enforcement_action(run_id: str, payload: EnforcementActionRequest):
    # Verify run exists
    run = None
    for r in run_history:
        if r["id"] == run_id:
            run = r
            break
            
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
        
    from app.core.config import settings
    ws_config = None
    if payload.workspace:
        for w in settings.get_workspaces():
            if w.get("name") == payload.workspace:
                ws_config = w
                break
                
    svc = SentinelService(workspace_config=ws_config)
    result = await svc.execute_action(
        action=payload.action,
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
        reason=payload.reason
    )
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to execute action"))
        
    return result

@router.post("/run")
async def trigger_run(background_tasks: BackgroundTasks, mode: str = "audit"):
    from app.core.config import settings
    workspaces = settings.get_workspaces()
    names = [w.get("name", "unknown") for w in workspaces]
    
    run_id = str(uuid.uuid4())
    run_record = {
        "id": run_id,
        "workspace": ", ".join(names),
        "environment": "multiple" if len(names) > 1 else workspaces[0].get("environment", "prod"),
        "mode": mode,
        "status": "running",
        "started_at": datetime.datetime.utcnow().isoformat(),
        "completed_at": None,
        "results": None
    }
    run_history.insert(0, run_record)

    def _do_run():
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            all_violations = []
            total_scanned = 0
            
            for ws_conf in workspaces:
                svc = SentinelService(workspace_config=ws_conf)
                ws_name = ws_conf.get("name", "unknown")
                ws_env = ws_conf.get("environment", "prod")
                
                results = loop.run_until_complete(svc.run_discovery_and_evaluation(ws_name, ws_env, mode))
                total_scanned += results.get("total_scanned", 0)
                all_violations.extend(results.get("violations", []))
                
            run_record["status"] = "completed"
            run_record["results"] = {
                "total_scanned": total_scanned,
                "total_violations": len(all_violations),
                "violations": all_violations
            }
        except Exception as e:
            run_record["status"] = "failed"
            run_record["error"] = str(e)
        finally:
            run_record["completed_at"] = datetime.datetime.utcnow().isoformat()
            loop.close()

    background_tasks.add_task(_do_run)
    return {"message": f"Run started in {mode} mode across {len(workspaces)} workspaces", "run_id": run_id}

@router.get("/runs")
async def get_runs():
    return run_history

@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    for r in run_history:
        if r["id"] == run_id:
            return r
    raise HTTPException(status_code=404, detail="Run not found")
