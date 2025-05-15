from __future__ import annotations

import asyncio
import json
from typing import Any
from dataclasses import dataclass
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.types as types

from flux_mcp.core.flux_engine import FluxEngine
from flux_mcp.core.transaction_manager import TransactionManager
from flux_mcp.core.memory_manager import MemoryManager


@dataclass
class ServerConfig:
    memory_mapped_threshold: int = 10 * 1024 * 1024  # 10MB
    chunk_size: int = 1024 * 1024  # 1MB
    worker_count: int = 15  
    cache_size: int = 1024 * 1024 * 1024  # 1GB
    gpu_enabled: bool = False  # Disable GPU for now since it has issues


class FluxServer:
    def __init__(self, config: ServerConfig | None = None) -> None:
        self.config: ServerConfig = config or ServerConfig()
        self.server: Server = Server("flux-text-editor")
        self.engine: FluxEngine = FluxEngine(self.config)
        self.transaction_manager: TransactionManager = TransactionManager()
        self.memory_manager: MemoryManager = MemoryManager(self.config)
        
        self._register_handlers()

    def _register_handlers(self) -> None:
        @self.server.list_tools()
        async def handle_list_tools() -> list[types.Tool]:
            return [
                types.Tool(
                    name="flux_read_file",
                    description="Read a file with automatic optimization for size",
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
                types.Tool(
                    name="flux_write_file",
                    description="Write to a file with automatic optimization",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path to write"},
                            "content": {"type": "string", "description": "Content to write"},
                            "encoding": {"type": "string", "description": "Text encoding (default: utf-8)"},
                            "create_dirs": {"type": "boolean", "description": "Create parent directories if needed"},
                            "simple_mode": {"type": "boolean", "description": "Skip transactions for small files (auto-detected if not set)"}
                        },
                        "required": ["path", "content"]
                    }
                ),
                types.Tool(
                    name="flux_search",
                    description="Search in files with automatic optimization",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path to search"},
                            "pattern": {"type": "string", "description": "Search pattern (regex or plain text)"},
                            "is_regex": {"type": "boolean", "description": "Whether pattern is regex"},
                            "case_sensitive": {"type": "boolean", "description": "Case sensitive search"},
                            "whole_word": {"type": "boolean", "description": "Match whole words only"},
                            "simple_mode": {"type": "boolean", "description": "Use fast path for simple searches (auto-detected if not set)"}
                        },
                        "required": ["path", "pattern"]
                    }
                ),
                types.Tool(
                    name="text_replace",
                    description="Advanced text replacement with hierarchical selection in Python files.\n\n" +
                    "⚠️ **CRITICAL USAGE GUIDE FOR AI/LLMs** ⚠️\n\n" +
                    "## How This Tool Works\n" +
                    "This tool precisely replaces code blocks by targeting classes/methods in Python files while preserving indentation.\n\n" +
                    "## CORRECT Usage Patterns\n" +
                    "1. **Basic targeting** - Simple string format:\n" +
                    "   * ✅ highlight='MyClass'  - replaces entire class\n" +
                    "   * ✅ highlight='MyClass.my_method'  - replaces specific method\n" +
                    "   * ❌ highlight='class MyClass'  - WRONG: no 'class' keyword\n" +
                    "   * ❌ highlight='def my_method()'  - WRONG: no 'def' keyword or parentheses\n\n" +
                    "2. **Standardized advanced targeting** - Always use 'target' key:\n" +
                    "   * ✅ highlight={\"target\": \"MyClass.method\"} - single target\n" +
                    "   * ✅ highlight={\"target\": [\"Class1\", \"Class2.method\"]} - multiple targets\n" +
                    "   * ✅ highlight={\"target\": \"MyClass\", \"occurrence\": 2} - 2nd occurrence\n" +
                    "   * ✅ highlight={\"target\": \"MyClass\", \"related_files\": [\"other.py\"]} - multi-file\n\n" +
                    "3. **replacement** - Can be string or dictionary for multiple targets:\n" +
                    "   * ✅ replace_with=\"\"\"def method(self) -> None:\\n    return True\"\"\"\n" +
                    "   * ✅ replace_with={\"Class1.method1\": \"\"\"def method1(self) -> None:\\n    return True\"\"\", \n" +
                    "              \"Class2.method2\": \"\"\"def method2(self) -> None:\\n    return False\"\"\"}\n\n" +
                    "4. **Always use triple quotes for code**:\n" +
                    "   * ✅ replace_with=\"\"\"def method(self) -> None:\\n    return True\"\"\"\n" +
                    "   * ❌ replace_with=\"def method(self) -> None:\\n    return True\"\n\n" +
                    "## Common Mistakes (AVOID THESE)\n" +
                    "* Targeting non-existent classes/methods (check available targets in error messages)\n" +
                    "* Mixed indentation (spaces vs tabs) in replacement code\n" +
                    "* Missing triple quotes (must use \"\"\" for proper whitespace preservation)\n" +
                    "* Incorrect escaping in replacement string (watch for \\n, \\t characters)\n" +
                    "* Not including complete definition line in replacement\n\n" +
                    "## Error Recovery\n" +
                    "If replacement fails, the tool will attempt to recover by:\n" +
                    "* Using fuzzy matching for targets\n" +
                    "* Suggesting similar targets when exact matches fail\n" +
                    "* Providing detailed error messages and contextual information",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Absolute file path to modify (must exist)"},
                            "highlight": {"description": "Target specification: 'ClassName' or 'ClassName.method_name' format ONLY. DO NOT include 'class' or 'def' keywords, parentheses, or colons. Can also be a dict with advanced targeting options like pattern, line_range, targets, occurrence."},
                            "replace_with": {"type": "string", "description": "Replacement text - MUST use triple quotes (\"\"\"...\"\"\"), include definition line, and use consistent indentation"},
                            "checkpoint": {"type": "string", "description": "Optional name for the checkpoint"},
                            "auto_checkpoint": {"type": "boolean", "description": "Whether to auto-generate a checkpoint name"}, 
                            "dry_run": {"type": "boolean", "description": "If True, preview changes without applying them"},
                            "batch_mode": {"type": "boolean", "description": "If True, process multiple related replacements together"},
                            "process_imports": {"type": "boolean", "description": "If True, analyze and manage imports for Python files"}
                        },
                        "required": ["path", "highlight", "replace_with"]
                    }
                )
            ]
        
        @self.server.call_tool()
        async def handle_tool_call(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
            try:
                if name == "flux_read_file":
                    result: str = await self.engine.read_file(**arguments)
                    return [types.TextContent(type="text", text=result)]
                
                elif name == "flux_write_file":
                    result: str = await self.engine.write_file(**arguments)
                    return [types.TextContent(type="text", text=result)]
                
                elif name == "flux_search":
                    results: list[dict[str, Any]] = await self.engine.search(**arguments)
                    json_result: str = json.dumps(results, indent=2)
                    return [types.TextContent(type="text", text=json_result)]
                
                elif name == "text_replace":
                    result: str = await self.engine.text_replace(**arguments)
                    return [types.TextContent(type="text", text=result)]
                
                else:
                    return [types.TextContent(type="text", text=f"Unknown tool: {name}")]
                    
            except Exception as e:
                import traceback
                error_msg: str = f"Error in {name}: {str(e)}\n{traceback.format_exc()}"
                return [types.TextContent(type="text", text=error_msg)]

    async def run(self) -> None:
        import mcp.server.stdio
        
        # Run the server using stdin/stdout streams
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream, 
                write_stream,
                InitializationOptions(
                    server_name="flux-text-editor",
                    server_version="0.3.0",  # Updated for enhanced text replacement
                    capabilities=self.server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )


if __name__ == "__main__":
    server: FluxServer = FluxServer()
    asyncio.run(server.run())
