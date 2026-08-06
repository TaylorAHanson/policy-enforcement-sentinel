"""Exceptions to the policies.

Two shapes, and the difference between them is the whole of the risk here.

A *resource* exception waives every failing rule for one named resource. It has
been the only shape since the beginning, and its blast radius is one thing
someone had to go and find the ID of.

A *pattern* exception waives one rule for one resource type in one workspace. It
is the shape people actually want — "service principals are allowed to own jobs
in the sandbox" is a sentence about a class, not about forty resources — but it
suppresses findings for resources that do not exist yet. So it is fenced: both
selectors are required and non-blank, and an expiry is compulsory, because a
permanent class-wide waiver is a policy change that never went through review.

The rule that matters most is that an empty selector matches nothing. Empty
must never mean "everything", here or anywhere else in this system.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session

from app.db.allowlist import MATCH_PATTERN, MATCH_RESOURCE, MATCH_TYPES, AllowlistModel
from app.db.session import get_db

router = APIRouter()


class AllowlistEntryCreate(BaseModel):
    resource_type: str
    workspace: str
    justification: str
    status: str = "approved"
    match_type: str = MATCH_RESOURCE
    #: Required for a resource exception, and must be absent for a pattern one.
    resource_id: Optional[str] = None
    #: Required for a pattern exception: the public rule ID, e.g. CST-CLU-005.
    rule_id: Optional[str] = None
    created_by: Optional[str] = None
    #: Null never expires. Permitted for a resource exception — a permanent
    #: waiver for one resource somebody had to name is a defensible thing to
    #: want — and refused for a pattern, where it would be a standing rule
    #: change with no review and no end.
    expires_at: Optional[datetime] = None

    @model_validator(mode="after")
    def check_shape(self):
        if self.match_type not in MATCH_TYPES:
            raise ValueError(
                f"match_type must be one of {', '.join(MATCH_TYPES)}, not {self.match_type!r}."
            )

        if not (self.resource_type or "").strip():
            raise ValueError("resource_type is required.")
        if not (self.workspace or "").strip():
            raise ValueError("workspace is required.")
        if not (self.justification or "").strip():
            raise ValueError("A justification is required.")

        if self.match_type == MATCH_RESOURCE:
            if not (self.resource_id or "").strip():
                raise ValueError("resource_id is required for a resource exception.")
            if self.rule_id:
                raise ValueError(
                    "rule_id applies to pattern exceptions. A resource exception "
                    "waives every failing rule for that resource."
                )
            return self

        # Pattern. Both selectors present and non-blank, checked here as well as
        # in Rego, because a row that reaches the database with a blank selector
        # is one policy-file edit away from waiving everything.
        if not (self.rule_id or "").strip():
            raise ValueError(
                "rule_id is required for a pattern exception. A pattern waives "
                "one rule, not every rule."
            )
        if self.resource_id:
            raise ValueError(
                "resource_id does not apply to a pattern exception. Use a "
                "resource exception to waive a single resource."
            )
        if self.expires_at is None:
            raise ValueError(
                "A pattern exception must expire. Waiving a rule for a whole "
                "class of resource with no end date is a policy change; make it "
                "in the policy, by pull request."
            )
        if self.expires_at <= _now_like(self.expires_at):
            raise ValueError("The expiry date is in the past.")
        return self


def _now_like(value: datetime) -> datetime:
    """``utcnow`` matched to whether the supplied value carries a timezone.

    Comparing an aware datetime to a naive one raises, and the client may send
    either. The stored column is naive.
    """
    return datetime.now(timezone.utc) if value.tzinfo else datetime.utcnow()


class AllowlistEntryUpdate(BaseModel):
    justification: Optional[str] = None
    status: Optional[str] = None
    #: Whether clearing this is allowed depends on the row's match_type, so the
    #: endpoint checks it once it knows which row is being edited.
    expires_at: Optional[datetime] = None


def _serialize(row: AllowlistModel) -> dict:
    return {
        "id": row.id,
        "resource_id": row.resource_id,
        "resource_type": row.resource_type,
        "workspace": row.workspace,
        "justification": row.justification,
        "status": row.status,
        "match_type": getattr(row, "match_type", None) or MATCH_RESOURCE,
        "rule_id": getattr(row, "rule_id", None),
        "created_by": getattr(row, "created_by", None),
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("", response_model=List[dict])
@router.get("/", response_model=List[dict])
def list_allowlist(db: Session = Depends(get_db)):
    return [_serialize(row) for row in db.query(AllowlistModel).all()]


@router.get("/resource-types", response_model=List[dict])
def resource_types():
    """The resource types a scan actually visits.

    Served rather than hardcoded in the form because the hardcoded list had
    drifted: it was missing six handlers and offered ``table``, which has never
    been one. An exception written against a type nothing discovers waives
    nothing, and looks like it worked.
    """
    from app.providers.databricks.handlers import HANDLER_REGISTRY

    return [
        {"value": name, "label": name.replace("_", " ")}
        for name in sorted(HANDLER_REGISTRY)
    ]


@router.get("/impact", response_model=List[dict])
def exception_impact(db: Session = Depends(get_db)):
    """How many findings each exception is currently suppressing.

    A pattern exception hides findings for resources that did not exist when it
    was written, so the number it covers only goes up, quietly — a suppressed
    finding looks exactly like a resource that passed. Counting them from the
    most recent scan is what makes that growth visible to whoever has to decide
    whether the waiver is still reasonable.
    """
    from app.db.sentinel_finding import SentinelFindingModel
    from app.db.sentinel_run import SentinelRunModel

    latest = (
        db.query(SentinelRunModel.id)
        .order_by(SentinelRunModel.started_at.desc())
        .first()
    )
    if latest is None:
        return []

    suppressed = (
        db.query(SentinelFindingModel)
        .filter(
            SentinelFindingModel.run_id == latest[0],
            SentinelFindingModel.effective_action == "SKIPPED_ALLOWLIST",
        )
        .all()
    )

    rows = []
    for entry in db.query(AllowlistModel).all():
        match_type = getattr(entry, "match_type", None) or MATCH_RESOURCE

        if match_type == MATCH_PATTERN:
            covered = [
                f
                for f in suppressed
                if f.workspace == entry.workspace
                and f.resource_type == entry.resource_type
                and f.policy_id == entry.rule_id
            ]
        else:
            covered = [
                f
                for f in suppressed
                if f.workspace == entry.workspace and f.resource_id == entry.resource_id
            ]

        rows.append(
            {
                "id": entry.id,
                "suppressed_findings": len(covered),
                "suppressed_resources": len({f.resource_id for f in covered}),
                "run_id": latest[0],
            }
        )

    return rows


@router.post("", response_model=dict)
@router.post("/", response_model=dict)
def create_allowlist_entry(entry: AllowlistEntryCreate, db: Session = Depends(get_db)):
    row = AllowlistModel(
        id=str(uuid.uuid4()),
        resource_id=(entry.resource_id or "").strip() or None,
        resource_type=entry.resource_type.strip(),
        workspace=entry.workspace.strip(),
        justification=entry.justification.strip(),
        status=entry.status,
        match_type=entry.match_type,
        rule_id=(entry.rule_id or "").strip() or None,
        created_by=(entry.created_by or "").strip() or None,
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

    fields = payload.model_dump(exclude_unset=True)

    # A pattern's expiry cannot be cleared, for the same reason it could not be
    # omitted at creation. Editing is the obvious way round a rule enforced only
    # on the way in.
    is_pattern = (getattr(row, "match_type", None) or MATCH_RESOURCE) == MATCH_PATTERN
    if is_pattern and "expires_at" in fields and fields["expires_at"] is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "A pattern exception must expire. Delete it instead if the rule "
                "should no longer apply to this class."
            ),
        )

    # `exclude_unset` rather than `exclude_none`: clearing an expiry to make an
    # exception permanent is a real edit, and the two are indistinguishable
    # otherwise.
    for field, value in fields.items():
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
