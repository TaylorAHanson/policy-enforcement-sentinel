import os
import glob
import httpx
import base64
import time
import logging
from fastapi import APIRouter, HTTPException, Query
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from app.core.actions import describe_ladder
from app.core.config import settings
from app.providers.opa.client import OpaProvider
from app.providers.opa.legacy_names import describe_migration
from app.services import policy_history, policy_registry, policy_sync
from app.services.github_errors import github_failure_detail

logger = logging.getLogger(__name__)

router = APIRouter()

class PolicyContent(BaseModel):
    content: str
    #: Commit a regenerated sibling `.md` alongside the Rego. On by default so
    #: the English and the policy cannot land in different commits.
    regenerate_explanation: bool = True

class PolicyValidatePayload(BaseModel):
    policy_name: str
    content: str

class EvalRequest(BaseModel):
    policy_name: str
    content: str
    query: str
    input_data: Dict[str, Any]

def get_github_client():
    if not settings.GITHUB_TOKEN:
        return None
    return httpx.AsyncClient(
        base_url="https://api.github.com",
        headers={
            "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
    )

@router.get("/config")
async def get_config():
    return {
        "github_enabled": bool(settings.GITHUB_TOKEN and settings.GITHUB_REPO),
        "target_branch": settings.GITHUB_TARGET_BRANCH
    }

@router.get("")
@router.get("/")
async def list_policies():
    if settings.GITHUB_TOKEN and settings.GITHUB_REPO:
        async with get_github_client() as client:
            url = f"/repos/{settings.GITHUB_REPO}/contents/{settings.GITHUB_POLICIES_DIR}?ref={settings.GITHUB_TARGET_BRANCH}"
            response = await client.get(url)
            if response.status_code == 200:
                contents = response.json()
                policies = [item["name"] for item in contents if item["name"].endswith(".rego") and item["type"] == "file"]
                return policies
            elif response.status_code == 404:
                # If directory doesn't exist yet
                return []
            else:
                logger.error(f"GitHub API error fetching policies: {response.text}")
                # Fallback to local on error
    
    policies_dir = settings.get_policies_dir
    if not os.path.exists(policies_dir):
        return []
    
    files = glob.glob(os.path.join(policies_dir, "*.rego"))
    policies = []
    for f in files:
        policies.append(os.path.basename(f))
    return policies

@router.post("/validate")
async def validate_policy(payload: PolicyValidatePayload):
    opa_provider = OpaProvider(settings.opa_provider_config())
    try:
        result = await opa_provider.check(payload.policy_name, payload.content)
        return result
    except Exception as e:
        return {"valid": False, "errors": [str(e)]}

@router.post("/evaluate")
async def evaluate_policy(payload: EvalRequest):
    """
    Evaluate arbitrary input against a live policy content.
    Useful for the playground.
    """
    opa_provider = OpaProvider(settings.opa_provider_config())
    
    try:
        result = await opa_provider.evaluate_content(
            policy_name=payload.policy_name,
            content=payload.content,
            query=payload.query,
            input_data=payload.input_data
        )
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}

# --- Metadata ---------------------------------------------------------------
#
# Declared before `/{policy_name}` so the path parameter does not swallow them.


@router.get("/metadata")
async def list_policy_metadata():
    """Every policy with its annotations and per-rule metadata.

    Also returns the action ladder, so the editor can render the tier of a
    requested action without hardcoding a copy of the registry that would drift
    from `core/actions.py`.
    """
    try:
        policies = policy_registry.load_policies()
    except policy_registry.PolicyRegistryError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return {
        "policies": [p.to_dict() for p in policies],
        "summary": policy_registry.registry_summary(),
        "action_ladder": describe_ladder(),
        "renamed_policies": describe_migration(),
        "history_available": policy_history.is_available(settings.get_policies_dir),
    }


@router.get("/metadata/summary")
async def policy_metadata_summary():
    try:
        return policy_registry.registry_summary()
    except policy_registry.PolicyRegistryError as e:
        raise HTTPException(status_code=503, detail=str(e))


# --- Working copy -----------------------------------------------------------


@router.get("/sync")
async def get_sync_status():
    """How current the local working copy is.

    The directory OPA evaluates is a copy of the target branch, so "when was
    this last pulled" is the difference between a merged PR being in force and
    it being invisible.
    """
    result = policy_sync.last_result()
    return {
        **result.to_dict(),
        "configured": policy_sync.is_configured(),
        "local_checkout": policy_sync.is_local_checkout(),
        "repo": settings.GITHUB_REPO,
        "branch": settings.GITHUB_TARGET_BRANCH,
        "interval_seconds": settings.POLICY_SYNC_INTERVAL_SECONDS,
    }


@router.post("/sync")
async def trigger_sync():
    """Rebuild the working copy from the target branch now."""
    result = await policy_sync.sync_policies()
    if result.status == "failed":
        raise HTTPException(status_code=502, detail=result.detail)
    return result.to_dict()


@router.get("/{policy_name}/metadata")
async def get_policy_metadata(policy_name: str):
    """One policy's metadata. Retired policy names resolve to their replacements."""
    try:
        descriptor = policy_registry.get_policy(policy_name)
    except policy_registry.PolicyRegistryError as e:
        raise HTTPException(status_code=503, detail=str(e))

    if descriptor is None:
        raise HTTPException(status_code=404, detail=f"No policy named {policy_name!r}.")

    payload = descriptor.to_dict()
    payload["uncommitted_changes"] = policy_history.uncommitted_changes(
        settings.get_policies_dir, descriptor.name
    )
    return payload


# --- Version history --------------------------------------------------------


@router.get("/{policy_name}/history")
async def get_policy_history(policy_name: str, limit: int = Query(50, ge=1, le=200)):
    """Commits that touched this policy, newest first.

    An environment with no git checkout is a normal deployment, not an error —
    it returns an empty list and says why.
    """
    policies_dir = settings.get_policies_dir
    try:
        revisions = policy_history.list_revisions(policies_dir, policy_name, limit=limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except policy_history.GitUnavailable as e:
        logger.info("Policy history unavailable for %s: %s", policy_name, e)
        return {"available": False, "reason": str(e), "revisions": []}

    return {
        "available": True,
        "revisions": [r.to_dict() for r in revisions],
        "uncommitted_changes": policy_history.uncommitted_changes(policies_dir, policy_name),
    }


@router.post("/{policy_name}/restore")
async def restore_policy_from_git(policy_name: str):
    """Throw away working-copy edits to a policy and take the committed text.

    This is the only write to the policies directory in the app, and it is a
    write that cannot introduce a rule: it can only put back what git already
    holds. An unreviewed edit sitting in the working copy is what a scan
    evaluates, so leaving no way to undo it would mean the only remedy was a
    shell.
    """
    policies_dir = settings.get_policies_dir
    try:
        content = policy_history.restore_from_head(policies_dir, policy_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except policy_history.GitUnavailable as e:
        raise HTTPException(
            status_code=409,
            detail=(
                f"The policies directory is not a git checkout, so there is "
                f"nothing to restore from: {e}"
            ),
        )
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Could not read the policy: {e}")

    logger.info("Restored %s from HEAD, discarding working-copy edits.", policy_name)
    return {"name": policy_name, "content": content, "uncommitted_changes": False}


@router.get("/{policy_name}/history/{sha}")
async def get_policy_at_revision(policy_name: str, sha: str, diff: bool = False):
    """The policy's text at a commit, or the diff that commit applied."""
    policies_dir = settings.get_policies_dir
    try:
        if diff:
            content = policy_history.get_revision_diff(policies_dir, policy_name, sha)
        else:
            content = policy_history.get_revision_content(policies_dir, policy_name, sha)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except policy_history.GitUnavailable as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"name": policy_name, "sha": sha, "diff": diff, "content": content}


@router.get("/{policy_name}")
async def get_policy(policy_name: str):
    if settings.GITHUB_TOKEN and settings.GITHUB_REPO:
        async with get_github_client() as client:
            url = f"/repos/{settings.GITHUB_REPO}/contents/{settings.GITHUB_POLICIES_DIR}/{policy_name}?ref={settings.GITHUB_TARGET_BRANCH}"
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                content = base64.b64decode(data["content"]).decode("utf-8")
                return {"name": policy_name, "content": content}
            elif response.status_code == 404:
                raise HTTPException(status_code=404, detail="Policy not found on GitHub")
            else:
                logger.error(f"GitHub API error fetching {policy_name}: {response.text}")

    policy_path = os.path.join(settings.get_policies_dir, policy_name)
    if not os.path.exists(policy_path):
        raise HTTPException(status_code=404, detail="Policy not found")
    
    with open(policy_path, "r") as f:
        content = f.read()
        
    return {"name": policy_name, "content": content}

# --- Pull requests ----------------------------------------------------------
#
# The only way a policy changes. The directory on disk is a working copy synced
# from the target branch by `services/policy_sync.py`; writing to it would give
# the user an edit that lasts until the container recycles and then vanishes
# without a trace. Every mutation below ends in a reviewable pull request.


def _repo_path(policy_name: str) -> str:
    return f"{settings.GITHUB_POLICIES_DIR}/{policy_name}"


def _explanation_repo_path(policy_name: str) -> str:
    """The sibling `.md` for a policy, as a path in the repository."""
    from app.agents.explain_rego import explanation_path

    return _repo_path(explanation_path("", policy_name))


def _require_github() -> None:
    if not (settings.GITHUB_TOKEN and settings.GITHUB_REPO):
        raise HTTPException(
            status_code=400,
            detail=(
                "GitHub is not configured, and policies are stored in git only. "
                "Set GITHUB_TOKEN and GITHUB_REPO to edit policies from here."
            ),
        )


def _github_error(response: httpx.Response, action: str) -> HTTPException:
    return HTTPException(
        status_code=502,
        detail=github_failure_detail(response.status_code, response.text, action),
    )


async def _fetch_committed(client: httpx.AsyncClient, policy_name: str) -> str:
    """A policy's contents on the target branch.

    Read from git rather than from the working copy so the diff in the pull
    request is against what is actually deployed, even if the local copy has
    drifted since the last sync.
    """
    resp = await client.get(
        f"/repos/{settings.GITHUB_REPO}/contents/{_repo_path(policy_name)}"
        f"?ref={settings.GITHUB_TARGET_BRANCH}"
    )
    if resp.status_code != 200:
        return ""
    return base64.b64decode(resp.json()["content"]).decode("utf-8")


async def _branch_from_target(client: httpx.AsyncClient, slug: str) -> str:
    """Cut a branch off the target branch and return its name."""
    ref_resp = await client.get(
        f"/repos/{settings.GITHUB_REPO}/git/refs/heads/{settings.GITHUB_TARGET_BRANCH}"
    )
    if ref_resp.status_code != 200:
        raise _github_error(
            ref_resp, f"Could not read the {settings.GITHUB_TARGET_BRANCH} branch"
        )

    branch = f"{slug}-{int(time.time())}"
    create_resp = await client.post(
        f"/repos/{settings.GITHUB_REPO}/git/refs",
        json={
            "ref": f"refs/heads/{branch}",
            "sha": ref_resp.json()["object"]["sha"],
        },
    )
    if create_resp.status_code != 201:
        raise _github_error(create_resp, f"Could not create the branch {branch}")
    return branch


async def _blob_sha(client: httpx.AsyncClient, path: str, ref: str) -> Optional[str]:
    """The blob SHA of a file on a ref, or None when it is not there."""
    resp = await client.get(f"/repos/{settings.GITHUB_REPO}/contents/{path}?ref={ref}")
    if resp.status_code == 200:
        return resp.json()["sha"]
    return None


async def _commit_file(
    client: httpx.AsyncClient, *, path: str, content: str, branch: str, message: str
) -> None:
    """Add or update one file on a branch.

    The SHA is looked up on the branch rather than on the target, so a second
    commit to the same branch does not collide with the first.
    """
    body: Dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "branch": branch,
    }
    existing = await _blob_sha(client, path, branch)
    if existing:
        body["sha"] = existing

    resp = await client.put(
        f"/repos/{settings.GITHUB_REPO}/contents/{path}", json=body
    )
    if resp.status_code not in (200, 201):
        raise _github_error(resp, f"Could not commit {path}")


async def _delete_file(
    client: httpx.AsyncClient, *, path: str, branch: str, message: str
) -> bool:
    """Remove one file on a branch. False when it was not there to begin with."""
    existing = await _blob_sha(client, path, branch)
    if not existing:
        return False

    # httpx's delete() takes no body, and the contents API needs the blob SHA.
    resp = await client.request(
        "DELETE",
        f"/repos/{settings.GITHUB_REPO}/contents/{path}",
        json={"message": message, "sha": existing, "branch": branch},
    )
    if resp.status_code != 200:
        raise _github_error(resp, f"Could not delete {path}")
    return True


async def _open_pr(
    client: httpx.AsyncClient, *, title: str, body: str, branch: str
) -> str:
    resp = await client.post(
        f"/repos/{settings.GITHUB_REPO}/pulls",
        json={
            "title": title,
            "body": body,
            "head": branch,
            "base": settings.GITHUB_TARGET_BRANCH,
        },
    )
    if resp.status_code != 201:
        raise _github_error(resp, "Could not open the pull request")
    return resp.json()["html_url"]


@router.post("/{policy_name}/pr")
async def create_policy_pr(policy_name: str, payload: PolicyContent):
    """Propose a policy change as a pull request.

    Commits two files: the Rego, and the plain-English explanation generated
    from it. They travel together so a reviewer who cannot read Rego still sees
    the consequence change from "warns the owner" to "revokes access" in the
    same diff, and so the explanation is never derived from a policy that was
    never merged.
    """
    _require_github()

    if not policy_name.endswith(".rego"):
        policy_name += ".rego"

    from app.agents.explain_rego import explain_rego
    from app.agents.pr_notes import pr_notes

    async with get_github_client() as client:
        current = await _fetch_committed(client, policy_name)

        # Built before any write so a reviewer sees the tier change and the
        # blast radius rather than "Automated PR". `pr_notes` falls back to a
        # factual template when the assistant is off, so the body never lands
        # without an escalation notice.
        try:
            notes = await pr_notes(policy_name, payload.content, old_content=current)
            pr_body = notes["body"]
            escalations = notes["escalations"]
        except Exception as e:
            logger.warning("Could not build PR notes for %s: %s", policy_name, e)
            pr_body = f"Updates `{policy_name}` from Policy Enforcement Sentinel."
            escalations = []

        title = f"Update governance policy: {policy_name}"
        if escalations:
            # The reviewer's list view shows the title and nothing else.
            title = f"[TIER ESCALATION] {title}"

        branch = await _branch_from_target(
            client, f"policy-{policy_name[: -len('.rego')]}"
        )

        await _commit_file(
            client,
            path=_repo_path(policy_name),
            content=payload.content,
            branch=branch,
            message=f"Update policy {policy_name}",
        )

        # Best-effort: the assistant being unavailable must not cost the user
        # their policy change. The editor shows when an explanation is missing.
        explanation_committed = False
        if payload.regenerate_explanation:
            try:
                text = await explain_rego(policy_name, payload.content)
            except Exception as e:
                logger.warning(
                    "Could not generate an explanation for %s: %s", policy_name, e
                )
                text = ""

            if text:
                await _commit_file(
                    client,
                    path=_explanation_repo_path(policy_name),
                    content=text.rstrip() + "\n",
                    branch=branch,
                    message=f"Update the plain-English version of {policy_name}",
                )
                explanation_committed = True

        pr_url = await _open_pr(client, title=title, body=pr_body, branch=branch)

    return {
        "message": "Pull request created successfully",
        "pr_url": pr_url,
        "branch": branch,
        "escalations": escalations,
        "explanation_committed": explanation_committed,
    }


@router.delete("/{policy_name}")
async def delete_policy(policy_name: str):
    """Propose retiring a policy as a pull request.

    Retiring a policy stops it enforcing everywhere, which is a bigger change
    than most edits and gets the same review.
    """
    _require_github()

    if not policy_name.endswith(".rego"):
        policy_name += ".rego"

    async with get_github_client() as client:
        current = await _fetch_committed(client, policy_name)
        if not current:
            raise HTTPException(
                status_code=404,
                detail=f"{policy_name} is not on {settings.GITHUB_TARGET_BRANCH}.",
            )

        branch = await _branch_from_target(
            client, f"retire-policy-{policy_name[: -len('.rego')]}"
        )

        message = f"Retire policy {policy_name}"
        await _delete_file(client, path=_repo_path(policy_name), branch=branch, message=message)
        await _delete_file(
            client,
            path=_explanation_repo_path(policy_name),
            branch=branch,
            message=f"Retire the plain-English version of {policy_name}",
        )

        body = (
            f"Retires `{policy_name}`.\n\n"
            "Once merged, the rules in this policy stop being evaluated and any "
            "resource they were flagging will no longer appear in scan results.\n\n"
            "<details><summary>The policy being removed</summary>\n\n"
            f"```rego\n{current.strip()}\n```\n\n</details>\n"
        )
        pr_url = await _open_pr(
            client, title=f"Retire governance policy: {policy_name}", body=body, branch=branch
        )

    return {
        "message": "Pull request created successfully",
        "pr_url": pr_url,
        "branch": branch,
    }
