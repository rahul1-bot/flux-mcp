#!/opt/homebrew/bin/python3.11
from flux_mcp.server import FluxServer
import asyncio

if __name__ == "__main__":
    server = FluxServer()
    asyncio.run(server.run())
