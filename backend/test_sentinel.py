import asyncio
from app.services.sentinel_service import SentinelService
from app.core.config import settings

async def main():
    print(f"POLICIES_DIR is: {settings.POLICIES_DIR}")
    import glob, os
    files = glob.glob(os.path.join(settings.POLICIES_DIR, "*.rego"))
    print(f"Glob found: {files}")
    
    svc = SentinelService()
    # Mocking DatabricksProvider and handlers is complex, but we can just run it and see the first few logs.
    res = await svc.run_discovery_and_evaluation("ws-enterprise-prod", "prod", "audit")
    print(res)

if __name__ == "__main__":
    asyncio.run(main())
