from __future__ import annotations

import asyncio
from typing import Any
from dataclasses import dataclass
from mcp.server import Server
from mcp.types import Tool, TextContent
from mcp.server.models import InitializationOptions

from flux_mcp.core.flux_engine import FluxEngine
from flux_mcp.core.transaction_manager import TransactionManager
from flux_mcp.core.memory_manager import MemoryManager


@dataclass
class ServerConfig:
    memory_mapped_threshold: int = 10 * 1024 * 1024  
    chunk_size: int = 1024 * 1024  
    worker_count: int = 15  
    cache_size: int = 1024 * 1024 * 1024  
    gpu_enabled: bool = True


class FluxServer:
    def __init__(self, config: ServerConfig | None = None) -> None:
        self.config: ServerConfig = config or ServerConfig()
        self.server: Server = Server("flux-text-editor")
        self.engine: FluxEngine = FluxEngine(self.config)
        self.transaction_manager: TransactionManager = TransactionManager()
        self.memory_manager: MemoryManager = MemoryManager(self.config)
        
        self._register_tools()
        self._register_handlers()

    def _register_tools(self) -> None:
        tools: list[Tool] = [
            Tool(
                name="flux_read_file",
                description="Read a file with encoding detection and memory mapping for large files",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path to read"},
                        "encoding": {"type": "string", "description": "Text encoding (auto-detected if not specified)"},
                        "start_line": {"type": "integer", "description": "Starting line number"},
                        "end_line": {"type": "integer", "description": "Ending line number"}
                    },
                    "required": ["path"]
                }
            ),
            Tool(
                name="flux_write_file",
                description="Write to a file atomically with transaction support",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path to write"},
                        "content": {"type": "string", "description": "Content to write"},
                        "encoding": {"type": "string", "description": "Text encoding (default: utf-8)"},
                        "create_dirs": {"type": "boolean", "description": "Create parent directories if needed"}
                    },
                    "required": ["path", "content"]
                }
            ),
            Tool(
                name="flux_search",
                description="Search in files with GPU acceleration for large-scale pattern matching",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path to search"},
                        "pattern": {"type": "string", "description": "Search pattern (regex or plain text)"},
                        "is_regex": {"type": "boolean", "description": "Whether pattern is regex"},
                        "case_sensitive": {"type": "boolean", "description": "Case sensitive search"},
                        "whole_word": {"type": "boolean", "description": "Match whole words only"}
                    },
                    "required": ["path", "pattern"]
                }
            ),
            Tool(
                name="flux_replace",
                description="Replace text in files with atomic transaction support",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path"},
                        "old_text": {"type": "string", "description": "Text to find"},
                        "new_text": {"type": "string", "description": "Replacement text"},
                        "is_regex": {"type": "boolean", "description": "Whether old_text is regex"},
                        "all_occurrences": {"type": "boolean", "description": "Replace all occurrences"}
                    },
                    "required": ["path", "old_text", "new_text"]
                }
            )
        ]
        
        for tool in tools:
            self.server.add_tool(tool)

    def _register_handlers(self) -> None:
        @self.server.initialize
        async def handle_initialize() -> InitializationOptions:
            return InitializationOptions(
                server_name="FLUX Text Editor MCP",
                server_version="1.0.0",
                capabilities=["file_operations", "search", "editing", "versioning"]
            )
        
        @self.server.call_tool
        async def handle_tool_call(name: str, arguments: dict[str, Any]) -> list[TextContent]:
            if name == "flux_read_file":
                result: str = await self.engine.read_file(**arguments)
                return [TextContent(type="text", text=result)]
            
            elif name == "flux_write_file":
                result: str = await self.engine.write_file(**arguments)
                return [TextContent(type="text", text=result)]
            
            elif name == "flux_search":
                results: list[dict[str, Any]] = await self.engine.search(**arguments)
                return [TextContent(type="text", text=str(results))]
            
            elif name == "flux_replace":
                result: str = await self.engine.replace(**arguments)
                return [TextContent(type="text", text=result)]
            
            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

    async def run(self) -> None:
        async with self.server:
            await self.server.run()


if __name__ == "__main__":
    server: FluxServer = FluxServer()
    asyncio.run(server.run())
