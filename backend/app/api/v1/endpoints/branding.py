import os
import yaml
from fastapi import APIRouter
from app.core.config import settings

router = APIRouter()

@router.get("/")
async def get_branding():
    # Attempt to locate configuration.yaml 
    # (could be in cwd if deployed, or one level up if running dev.sh from backend/)
    config_paths = [
        os.path.join(os.getcwd(), "configuration.yaml"),
        os.path.join(os.getcwd(), "..", "configuration.yaml")
    ]
    
    for config_path in config_paths:
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    config = yaml.safe_load(f)
                    return config.get("branding", {})
            except Exception:
                pass
                
    # Fallback default
    return {
        "name": "Policy Enforcement Sentinel",
        "primary_color": "#3b82f6",
        "secondary_color": "#1f2937"
    }
