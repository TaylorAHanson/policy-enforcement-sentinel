import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.mcp_server import mcp

if __name__ == "__main__":
    mcp.run(transport='stdio')
