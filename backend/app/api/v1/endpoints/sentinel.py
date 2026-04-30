from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import Dict, Any, List
import uuid
import datetime
from app.services.sentinel_service import SentinelService

router = APIRouter()

# In-memory run store for simplicity since we stripped the database tables
# You can upgrade this to SQLite if needed
run_history = []

@router.post("/run")
async def trigger_run(background_tasks: BackgroundTasks, workspace: str = "ws-enterprise-prod", env: str = "prod", mode: str = "audit"):
    run_id = str(uuid.uuid4())
    run_record = {
        "id": run_id,
        "workspace": workspace,
        "environment": env,
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
            svc = SentinelService()
            results = loop.run_until_complete(svc.run_discovery_and_evaluation(workspace, env, mode))
            run_record["status"] = "completed"
            run_record["results"] = results
        except Exception as e:
            run_record["status"] = "failed"
            run_record["error"] = str(e)
        finally:
            run_record["completed_at"] = datetime.datetime.utcnow().isoformat()
            loop.close()

    background_tasks.add_task(_do_run)
    return {"message": f"Run started in {mode} mode", "run_id": run_id}

@router.get("/runs")
async def get_runs():
    return run_history

@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    for r in run_history:
        if r["id"] == run_id:
            return r
    raise HTTPException(status_code=404, detail="Run not found")
