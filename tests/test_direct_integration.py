from __future__ import annotations

# Test direct FLUX usage without MCP
import sys
sys.path.append('/Users/rahulsawhney/LocalCode/mcp-servers/Flux')

from flux_mcp.server import FluxServer, ServerConfig
from flux_mcp.core.flux_engine import FluxEngine
import asyncio

async def test_direct():
    config = ServerConfig()
    engine = FluxEngine(config)
    
    print("=== Testing Write ===")
    result = await engine.write_file(
        "/Users/rahulsawhney/LocalCode/mcp-servers/Flux/test_direct.txt",
        "Direct test content\nLine 2\nPattern ABC here",
        create_dirs=True
    )
    print(result)
    
    print("\n=== Testing Read ===")
    content = await engine.read_file(
        "/Users/rahulsawhney/LocalCode/mcp-servers/Flux/test_direct.txt"
    )
    print(content)
    
    print("\n=== Testing Search ===")
    results = await engine.search(
        "/Users/rahulsawhney/LocalCode/mcp-servers/Flux/test_direct.txt",
        "ABC",
        is_regex=False
    )
    print(results)

if __name__ == "__main__":
    asyncio.run(test_direct())
