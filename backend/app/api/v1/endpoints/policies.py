import os
import glob
import httpx
import base64
import time
import logging
from fastapi import APIRouter, HTTPException
from typing import Dict, Any, List
from pydantic import BaseModel
from app.core.config import settings
from app.providers.opa.client import OpaProvider

logger = logging.getLogger(__name__)

router = APIRouter()

class PolicyContent(BaseModel):
    content: str

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
    
    policies_dir = os.path.join(os.getcwd(), settings.POLICIES_DIR)
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

    policy_path = os.path.join(os.getcwd(), settings.POLICIES_DIR, policy_name)
    if not os.path.exists(policy_path):
        raise HTTPException(status_code=404, detail="Policy not found")
    
    with open(policy_path, "r") as f:
        content = f.read()
        
    return {"name": policy_name, "content": content}

@router.post("/{policy_name}/pr")
async def create_policy_pr(policy_name: str, payload: PolicyContent):
    if not (settings.GITHUB_TOKEN and settings.GITHUB_REPO):
        raise HTTPException(status_code=400, detail="GitHub integration is not configured")
        
    if not policy_name.endswith(".rego"):
        policy_name += ".rego"
        
    async with get_github_client() as client:
        # 1. Get base SHA
        ref_url = f"/repos/{settings.GITHUB_REPO}/git/refs/heads/{settings.GITHUB_TARGET_BRANCH}"
        ref_resp = await client.get(ref_url)
        if ref_resp.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Failed to get target branch {settings.GITHUB_TARGET_BRANCH}: {ref_resp.text}")
        base_sha = ref_resp.json()["object"]["sha"]
        
        # 2. Create new branch
        branch_name = f"update-policy-{policy_name.replace('.rego', '')}-{int(time.time())}"
        create_ref_resp = await client.post(
            f"/repos/{settings.GITHUB_REPO}/git/refs",
            json={"ref": f"refs/heads/{branch_name}", "sha": base_sha}
        )
        if create_ref_resp.status_code != 201:
            raise HTTPException(status_code=500, detail=f"Failed to create branch {branch_name}: {create_ref_resp.text}")
            
        # 3. Create commit (create or update file)
        file_url = f"/repos/{settings.GITHUB_REPO}/contents/{settings.GITHUB_POLICIES_DIR}/{policy_name}?ref={settings.GITHUB_TARGET_BRANCH}"
        file_resp = await client.get(file_url)
        file_sha = None
        if file_resp.status_code == 200:
            file_sha = file_resp.json()["sha"]
            
        update_data = {
            "message": f"Update policy {policy_name}",
            "content": base64.b64encode(payload.content.encode("utf-8")).decode("utf-8"),
            "branch": branch_name
        }
        if file_sha:
            update_data["sha"] = file_sha
            
        update_resp = await client.put(
            f"/repos/{settings.GITHUB_REPO}/contents/{settings.GITHUB_POLICIES_DIR}/{policy_name}",
            json=update_data
        )
        if update_resp.status_code not in [200, 201]:
            raise HTTPException(status_code=500, detail=f"Failed to commit file: {update_resp.text}")
            
        # 4. Open PR
        pr_resp = await client.post(
            f"/repos/{settings.GITHUB_REPO}/pulls",
            json={
                "title": f"Update Governance Policy: {policy_name}",
                "body": f"Automated PR from Policy Enforcement Sentinel to update `{policy_name}`.",
                "head": branch_name,
                "base": settings.GITHUB_TARGET_BRANCH
            }
        )
        if pr_resp.status_code != 201:
            raise HTTPException(status_code=500, detail=f"Failed to create PR: {pr_resp.text}")
            
        pr_url = pr_resp.json()["html_url"]
        return {"message": "Pull request created successfully", "pr_url": pr_url}

@router.post("/{policy_name}")
async def save_policy(policy_name: str, payload: PolicyContent):
    if not policy_name.endswith(".rego"):
        policy_name += ".rego"
        
    policies_dir = os.path.join(os.getcwd(), settings.POLICIES_DIR)
    if not os.path.exists(policies_dir):
        os.makedirs(policies_dir)
        
    policy_path = os.path.join(policies_dir, policy_name)
    
    with open(policy_path, "w") as f:
        f.write(payload.content)
        
    return {"message": "Policy saved locally", "name": policy_name}

@router.delete("/{policy_name}")
async def delete_policy(policy_name: str):
    policy_path = os.path.join(os.getcwd(), settings.POLICIES_DIR, policy_name)
    if os.path.exists(policy_path):
        os.remove(policy_path)
        return {"message": "Policy deleted"}
    raise HTTPException(status_code=404, detail="Policy not found")
