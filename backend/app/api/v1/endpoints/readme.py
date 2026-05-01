import os
from fastapi import APIRouter, HTTPException

router = APIRouter()

@router.get("")
@router.get("/")
async def get_readme():
    """
    Returns the content of the README.md file at the root of the project.
    """
    readme_paths = [
        os.path.join(os.getcwd(), "README.md"),
        os.path.join(os.getcwd(), "..", "README.md")
    ]
    
    for path in readme_paths:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return {"content": f.read()}
                
    raise HTTPException(status_code=404, detail="README.md not found")
