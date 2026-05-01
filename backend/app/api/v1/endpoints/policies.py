import os
import glob
from fastapi import APIRouter, HTTPException
from typing import Dict, Any, List
from pydantic import BaseModel
from app.core.config import settings
from app.providers.opa.client import OpaProvider

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

@router.get("/")
async def list_policies():
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
    policy_path = os.path.join(os.getcwd(), settings.POLICIES_DIR, policy_name)
    if not os.path.exists(policy_path):
        raise HTTPException(status_code=404, detail="Policy not found")
    
    with open(policy_path, "r") as f:
        content = f.read()
        
    return {"name": policy_name, "content": content}

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
        
    return {"message": "Policy saved", "name": policy_name}

@router.delete("/{policy_name}")
async def delete_policy(policy_name: str):
    policy_path = os.path.join(os.getcwd(), settings.POLICIES_DIR, policy_name)
    if os.path.exists(policy_path):
        os.remove(policy_path)
        return {"message": "Policy deleted"}
    raise HTTPException(status_code=404, detail="Policy not found")
