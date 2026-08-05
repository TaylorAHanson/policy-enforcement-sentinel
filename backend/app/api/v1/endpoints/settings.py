"""Admin settings API.

Exposes the schema in ``settings_store.EDITABLE_FIELDS`` so the frontend renders
the form from the backend's declaration rather than keeping its own copy in
sync. Adding a setting is a one-line change in ``EDITABLE_FIELDS`` and it
appears in the UI.
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core import settings_store
from app.core.actions import describe_ladder
from app.core.config import settings
from app.core.enforcement import describe_gates
from app.db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


class SettingUpdate(BaseModel):
    value: Any
    updated_by: Optional[str] = None


class BulkSettingUpdate(BaseModel):
    values: Dict[str, Any]
    updated_by: Optional[str] = None


@router.get("")
def get_settings(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """The editable schema, current values, and the safety model's documentation."""
    fields = settings_store.describe(db)

    groups: List[Dict[str, Any]] = []
    for field in fields:
        group = next((g for g in groups if g["name"] == field["group"]), None)
        if group is None:
            group = {
                "name": field["group"],
                "danger": bool(field.get("danger")),
                "fields": [],
            }
            groups.append(group)
        group["fields"].append(field)

    return {
        "groups": groups,
        "enforcement_enabled": bool(settings.ENFORCEMENT_ENABLED),
        "destructive_workspaces": settings.destructive_workspaces(),
        "gates": describe_gates(),
        "action_ladder": describe_ladder(),
    }


@router.get("/cron-preview")
def preview_cron(expression: str = "") -> Dict[str, Any]:
    """Check a cron expression and say when it would next fire.

    Declared before the parameterised routes so `/cron-preview` is not read as a
    setting key.

    This exists so the answer arrives while the admin is typing. A schedule is
    the one setting whose effect is invisible for hours after saving it, and
    "0 2 * * *" versus "2 0 * * *" is a twenty-two hour mistake that looks
    identical on the page.
    """
    problem = settings_store.validate_cron(expression)
    return {
        "expression": expression,
        "valid": problem is None,
        "error": problem,
        "disabled": not expression.strip(),
        "next_runs": settings_store.next_cron_runs(expression),
    }


@router.put("/{key}")
def update_setting(
    key: str, payload: SettingUpdate, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    try:
        value = settings_store.set_override(db, key, payload.value, payload.updated_by)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    db.commit()
    return {"key": key, "value": value, "danger": key in settings_store.DANGER_KEYS}


@router.put("")
def update_settings(
    payload: BulkSettingUpdate, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    applied: Dict[str, Any] = {}
    errors: Dict[str, str] = {}

    for key, value in payload.values.items():
        try:
            applied[key] = settings_store.set_override(db, key, value, payload.updated_by)
        except ValueError as e:
            errors[key] = str(e)

    # Commit whatever was valid rather than discarding the whole batch; the
    # response says exactly what did and didn't land.
    db.commit()

    if errors and not applied:
        raise HTTPException(status_code=400, detail=errors)

    return {"applied": applied, "errors": errors}


@router.delete("/{key}")
def reset_setting(key: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Drop an override so the value falls back to the deploy-time default."""
    if key not in settings_store.FIELDS_BY_KEY:
        raise HTTPException(status_code=404, detail=f"{key} is not an editable setting")

    settings_store.clear_override(db, key)
    db.commit()
    return {"key": key, "value": getattr(settings, key, None), "overridden": False}
