import uuid
from typing import List, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.allowlist import AllowlistModel
from pydantic import BaseModel
from datetime import datetime

router = APIRouter()

class AllowlistEntryCreate(BaseModel):
    resource_id: str
    resource_type: str
    workspace: str
    justification: str
    status: str = "approved"

class AllowlistEntryUpdate(BaseModel):
    justification: str | None = None
    status: str | None = None

@router.get("/", response_model=List[dict])
def list_allowlist(db: Session = Depends(get_db)):
    records = db.query(AllowlistModel).all()
    return [
        {
            "id": r.id,
            "resource_id": r.resource_id,
            "resource_type": r.resource_type,
            "workspace": r.workspace,
            "justification": r.justification,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in records
    ]

@router.post("/", response_model=dict)
def create_allowlist_entry(entry: AllowlistEntryCreate, db: Session = Depends(get_db)):
    db_obj = AllowlistModel(
        id=str(uuid.uuid4()),
        resource_id=entry.resource_id,
        resource_type=entry.resource_type,
        workspace=entry.workspace,
        justification=entry.justification,
        status=entry.status
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return {
        "id": db_obj.id,
        "resource_id": db_obj.resource_id,
        "resource_type": db_obj.resource_type,
        "workspace": db_obj.workspace,
        "justification": db_obj.justification,
        "status": db_obj.status,
    }

@router.delete("/{entry_id}", response_model=dict)
def delete_allowlist_entry(entry_id: str, db: Session = Depends(get_db)):
    db_obj = db.query(AllowlistModel).filter(AllowlistModel.id == entry_id).first()
    if not db_obj:
        raise HTTPException(status_code=404, detail="Allowlist entry not found")
    
    db.delete(db_obj)
    db.commit()
    return {"success": True, "message": "Entry deleted"}
