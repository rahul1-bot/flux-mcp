from __future__ import annotations

import asyncio
import sys
import os

# Add the parent directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flux_mcp.server import FluxServer

if __name__ == "__main__":
    server = FluxServer()
    asyncio.run(server.run())
