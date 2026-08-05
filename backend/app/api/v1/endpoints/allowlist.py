import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.allowlist import AllowlistModel
from app.db.session import get_db

router = APIRouter()


class AllowlistEntryCreate(BaseModel):
    resource_id: str
    resource_type: str
    workspace: str
    justification: str
    status: str = "approved"
    #: Null never expires. An exception with no end date is a policy change
    #: nobody wrote down, so the UI encourages setting one — but permanent
    #: exceptions are legitimate and this does not force the issue.
    expires_at: Optional[datetime] = None


class AllowlistEntryUpdate(BaseModel):
    justification: Optional[str] = None
    status: Optional[str] = None
    expires_at: Optional[datetime] = None


def _serialize(row: AllowlistModel) -> dict:
    return {
        "id": row.id,
        "resource_id": row.resource_id,
        "resource_type": row.resource_type,
        "workspace": row.workspace,
        "justification": row.justification,
        "status": row.status,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("", response_model=List[dict])
@router.get("/", response_model=List[dict])
def list_allowlist(db: Session = Depends(get_db)):
    return [_serialize(row) for row in db.query(AllowlistModel).all()]


@router.post("", response_model=dict)
@router.post("/", response_model=dict)
def create_allowlist_entry(entry: AllowlistEntryCreate, db: Session = Depends(get_db)):
    row = AllowlistModel(
        id=str(uuid.uuid4()),
        resource_id=entry.resource_id,
        resource_type=entry.resource_type,
        workspace=entry.workspace,
        justification=entry.justification,
        status=entry.status,
        expires_at=entry.expires_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.patch("/{entry_id}", response_model=dict)
def update_allowlist_entry(
    entry_id: str, payload: AllowlistEntryUpdate, db: Session = Depends(get_db)
):
    row = db.query(AllowlistModel).filter(AllowlistModel.id == entry_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Allowlist entry not found")

    # `exclude_unset` rather than `exclude_none`: clearing an expiry to make an
    # exception permanent is a real edit, and the two are indistinguishable
    # otherwise.
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)

    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.delete("/{entry_id}", response_model=dict)
def delete_allowlist_entry(entry_id: str, db: Session = Depends(get_db)):
    row = db.query(AllowlistModel).filter(AllowlistModel.id == entry_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Allowlist entry not found")

    db.delete(row)
    db.commit()
    return {"success": True, "message": "Entry deleted"}
