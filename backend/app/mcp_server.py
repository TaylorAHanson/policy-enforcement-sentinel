from mcp.server.fastmcp import FastMCP
import asyncio
from app.services.sentinel_service import SentinelService

mcp = FastMCP("Policy Enforcement Sentinel", description="Policy enforcement MCP server")

@mcp.tool()
async def trigger_sentinel_run(workspace: str = "ws-enterprise-prod", environment: str = "prod", mode: str = "audit") -> str:
    """Trigger a sentinel run to discover resources and evaluate them against policies."""
    svc = SentinelService()
    try:
        results = await svc.run_discovery_and_evaluation(workspace, environment, mode)
        total = results.get("total_violations", 0)
        return f"Sentinel run completed successfully in {mode} mode. Found {total} violations."
    except Exception as e:
        return f"Sentinel run failed: {str(e)}"
