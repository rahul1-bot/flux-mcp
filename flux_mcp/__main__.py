from __future__ import annotations

import asyncio
from flux_mcp.server import FluxServer


if __name__ == "__main__":
    server = FluxServer()
    asyncio.run(server.run())
