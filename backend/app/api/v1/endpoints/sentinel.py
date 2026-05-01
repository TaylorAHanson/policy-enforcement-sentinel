from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import uuid
import datetime
from sqlalchemy.orm import Session
from app.db.session import get_db, get_lakebase_session
from app.db.sentinel_run import SentinelRunModel
from app.services.sentinel_service import SentinelService

router = APIRouter()

class EnforcementActionRequest(BaseModel):
    resource_id: str
    resource_type: str
    action: str
    policy_name: str
    reason: str = "Manual execution via UI"
    workspace: Optional[str] = None

@router.post("/runs/{run_id}/enforcement-action")
async def execute_enforcement_action(run_id: str, payload: EnforcementActionRequest, db: Session = Depends(get_db)):
    # Verify run exists in Lakebase
    run = db.query(SentinelRunModel).filter(SentinelRunModel.id == run_id).first()
            
    if not run:
        raise HTTPException(status_code=404, detail="Run not found in database")
        
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
async def trigger_run(background_tasks: BackgroundTasks, mode: str = "audit", db: Session = Depends(get_db)):
    from app.core.config import settings
    workspaces = settings.get_workspaces()
    names = [w.get("name", "unknown") for w in workspaces]
    
    run_id = str(uuid.uuid4())
    
    # Store initial run in database
    run_record = SentinelRunModel(
        id=run_id,
        workspace=", ".join(names),
        environment="multiple" if len(names) > 1 else workspaces[0].get("environment", "prod"),
        mode=mode,
        status="running",
        started_at=datetime.datetime.utcnow(),
    )
    db.add(run_record)
    db.commit()

    def _do_run():
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Get a fresh session for the background task
        bg_db = get_lakebase_session()
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
            
            # Fetch and update the run in db
            run = bg_db.query(SentinelRunModel).filter(SentinelRunModel.id == run_id).first()
            if run:
                run.status = "completed"
                run.results = {
                    "total_scanned": total_scanned,
                    "total_violations": len(all_violations),
                    "violations": all_violations
                }
                run.completed_at = datetime.datetime.utcnow()
                bg_db.commit()
                
        except Exception as e:
            bg_db.rollback()
            run = bg_db.query(SentinelRunModel).filter(SentinelRunModel.id == run_id).first()
            if run:
                run.status = "failed"
                run.error = str(e)
                run.completed_at = datetime.datetime.utcnow()
                bg_db.commit()
        finally:
            bg_db.close()
            loop.close()

    background_tasks.add_task(_do_run)
    return {"message": f"Run started in {mode} mode across {len(workspaces)} workspaces", "run_id": run_id}

@router.get("/runs")
async def get_runs(db: Session = Depends(get_db)):
    # Returns the 50 most recent runs
    runs = db.query(SentinelRunModel).order_by(SentinelRunModel.started_at.desc()).limit(50).all()
    # Serialize to dicts for FastAPI JSON encoding
    return [
        {
            "id": r.id,
            "workspace": r.workspace,
            "environment": r.environment,
            "mode": r.mode,
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "error": r.error,
            "results": r.results
        } for r in runs
    ]

@router.get("/runs/{run_id}")
async def get_run(run_id: str, db: Session = Depends(get_db)):
    r = db.query(SentinelRunModel).filter(SentinelRunModel.id == run_id).first()
    if r:
        return {
            "id": r.id,
            "workspace": r.workspace,
            "environment": r.environment,
            "mode": r.mode,
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "error": r.error,
            "results": r.results
        }
    raise HTTPException(status_code=404, detail="Run not found in database")
