"""Running the tests from the app.

Two things are exposed. Fixture runs put made-up resources through the real
policies, which is how you find out whether a rule fires on the thing you think
it fires on without waiting for a scan of somebody's real estate. The pytest
runner runs the suite that ships with the app.

Neither reaches a workspace. The fixture runner has no client to reach one with,
and pytest runs the mocked suite in a subprocess.
"""
from __future__ import annotations

import logging
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services import (
    field_reconciliation,
    pytest_runner,
    rule_diagnosis,
    synthetic_estate,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class SyntheticRequest(BaseModel):
    #: Run only these fixtures. Empty runs all of them.
    fixtures: List[str] = []
    #: Narrow to one resource type, which is how the editor scopes a run to the
    #: policy that is open.
    resource_type: Optional[str] = None
    #: Unsaved editor content to test instead of the committed file. Both must
    #: be present together; a name with no content would silently blank a
    #: policy for the duration of the run.
    draft_policy: Optional[str] = None
    draft_content: Optional[str] = None


class CaptureRequest(BaseModel):
    #: The run to capture from. Omitted means the most recent one.
    run_id: Optional[str] = None
    #: Capture only these resources. Empty takes whatever the run holds.
    resource_ids: List[str] = []
    limit: int = 25
    #: Replace owner email addresses. A fixture is a file in a repository.
    anonymise: bool = True


class PromoteRequest(BaseModel):
    #: Defaults to a name describing what the test demonstrates.
    target_name: Optional[str] = None
    #: Write it even though identifying values survived scrubbing. Deliberately
    #: awkward to reach: there is no UI for it.
    allow_survivors: bool = False


class PytestRequest(BaseModel):
    suite: str = "all"
    #: Passed to pytest's -k. Handy for re-running one failure.
    keyword: Optional[str] = None


@router.get("/fixtures")
def list_fixtures():
    """What is available to run, without running it."""
    fixtures = synthetic_estate.load_fixtures()
    return {
        "fixtures": [
            {
                "name": f.name,
                "description": f.description,
                "resource_type": f.resource_type,
                "workspace": f.workspace,
                "environment": f.environment,
                "source": f.source,
                "captured": f.captured,
                "expects_fires": f.fires,
                "expects_passes": f.passes,
            }
            for f in fixtures
        ],
        "directory": synthetic_estate.fixtures_dir(),
        "captures_directory": synthetic_estate.captures_dir(),
    }


@router.post("/synthetic")
async def run_synthetic(payload: Optional[SyntheticRequest] = None):
    """Evaluate the fixtures against the policies, or against a draft."""
    payload = payload or SyntheticRequest()

    draft = None
    if payload.draft_policy or payload.draft_content is not None:
        if not payload.draft_policy or payload.draft_content is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Testing a draft needs both draft_policy and draft_content. "
                    "A name without content would evaluate the fixtures against "
                    "an empty policy and report that nothing fires."
                ),
            )
        draft = synthetic_estate.Draft(
            policy_name=payload.draft_policy, content=payload.draft_content
        )

    try:
        return await synthetic_estate.run_all(
            only=payload.fixtures or None,
            resource_type=payload.resource_type,
            draft=draft,
        )
    except Exception as e:
        logger.exception("The synthetic run failed.")
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/coverage")
def coverage(resource_type: Optional[str] = None, policy: Optional[str] = None):
    """Which rules are shown working, and why the rest are not.

    A rule with no test is not a passing rule, it is an untested one, and the
    two look identical on a green results page. But "no test" is not one
    problem: a rule waiting on data the scanner does not collect, a rule for a
    resource type nothing scans, and a rule that reads real data and still never
    matches need three different people to do three different things. Only the
    last is a bug in the rule.

    So each rule comes back with the reason it is not working and what would fix
    it. See ``services/rule_diagnosis.py``.
    """
    try:
        return rule_diagnosis.diagnose(
            resource_type=resource_type, policy_name=policy
        )
    except Exception as e:
        logger.exception("Coverage lookup failed.")
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/drift")
def drift(db: Session = Depends(get_db)):
    """Where the field catalogue and the real estate disagree.

    Every other check here is made *against* ``discovered_fields``: policies are
    validated against it, fixtures may not invent a field outside it, and the
    coverage diagnosis decides a rule is workable by consulting it. It is a
    hand-written docstring on a Python class and nothing has ever confirmed it.

    This compares it to what the handlers emitted on the last real scan. It
    needs a scan to have happened — against fixtures it would only confirm that
    fixtures were written to match the catalogue, which is true by construction
    and proves nothing.
    """
    try:
        return field_reconciliation.report(db)
    except Exception as e:
        logger.exception("Drift report failed.")
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/capture")
def capture(payload: Optional[CaptureRequest] = None, db: Session = Depends(get_db)):
    """Write fixtures from the resources a real scan already recorded.

    The fixtures land in the working copy, which the next restart rebuilds from
    git — the same as policies. They are a starting point to read, edit, and
    commit through a pull request, not a persistent artefact.
    """
    payload = payload or CaptureRequest()
    try:
        written = synthetic_estate.capture_from_run(
            db,
            run_id=payload.run_id,
            resource_ids=payload.resource_ids or None,
            limit=max(1, min(payload.limit, 200)),
            anonymise=payload.anonymise,
        )
    except Exception as e:
        logger.exception("Fixture capture failed.")
        raise HTTPException(status_code=502, detail=str(e))

    return {
        "captured": written,
        "count": len(written),
        "directory": synthetic_estate.captures_dir(),
        "note": (
            "Local and gitignored. These record what the policies do today, "
            "including anything they get wrong, and they are named after real "
            "resources. Promote one to scrub the names and ship it."
        ),
    }


@router.get("/captures")
def list_captures():
    """The local captures, and what promoting each would write.

    The plan is computed per capture so the page can show what would change
    before anybody commits to it, and can grey out the ones that would be
    refused.
    """
    out = []
    # Grows as the list is planned, so two captures never propose the same name.
    taken = synthetic_estate._shipped_names()
    for fixture in synthetic_estate.load_fixtures(
        synthetic_estate.captures_dir()
    ):
        entry = {
            "name": fixture.name,
            "resource_type": fixture.resource_type,
            "expects_fires": fixture.fires,
            "expects_passes": fixture.passes,
        }
        try:
            plan = synthetic_estate.plan_promotion(fixture.name, taken=taken)
            taken.add(plan["target_name"])
            entry["target_name"] = plan["target_name"]
            entry["replacements"] = plan["replacements"]
            entry["survivors"] = plan["survivors"]
            entry["withheld"] = plan["withheld"]
        except synthetic_estate.FixtureError as e:
            entry["error"] = str(e)
        out.append(entry)

    return {
        "captures": out,
        "count": len(out),
        "directory": synthetic_estate.captures_dir(),
    }


@router.post("/captures/{name}/promote")
async def promote_capture(name: str, payload: Optional[PromoteRequest] = None):
    """Scrub a capture's names and move it into the shipped tests.

    The one path from a real estate into a committed file, so it fails closed:
    it refuses if an identifying word survived scrubbing, and it refuses if
    replacing the names changed what the policies do to the resource.
    """
    payload = payload or PromoteRequest()
    try:
        return await synthetic_estate.promote(
            name,
            target_name=payload.target_name,
            allow_survivors=payload.allow_survivors,
        )
    except synthetic_estate.FixtureError as e:
        # 422, not 502: the request was understood and deliberately refused.
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Promoting a capture failed.")
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/suites")
def list_suites():
    """Which suites this deployment actually has on disk."""
    root = pytest_runner.backend_dir()
    return {
        "suites": [
            {"name": name, "path": path, "available": os.path.isdir(os.path.join(root, path))}
            for name, path in pytest_runner.SUITES.items()
        ]
    }


@router.post("/pytest")
async def run_pytest(payload: Optional[PytestRequest] = None):
    """Run the Python suite in a subprocess and return the parsed report."""
    payload = payload or PytestRequest()
    try:
        return await pytest_runner.run(payload.suite, payload.keyword)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        # A second run while one is going. 409 rather than 500: the request is
        # fine, the timing is not.
        raise HTTPException(status_code=409, detail=str(e))
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except Exception as e:
        logger.exception("The pytest run failed.")
        raise HTTPException(status_code=502, detail=str(e))
