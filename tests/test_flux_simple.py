from __future__ import annotations

import asyncio
import tempfile
import time
import os
from pathlib import Path
from typing import Any
from dataclasses import dataclass

from flux_mcp.server import FluxServer, ServerConfig


@dataclass
class TestResult:
    test_name: str
    passed: bool
    duration: float
    error: str | None = None
    details: dict[str, Any] | None = None


class FluxMCPTester:
    def __init__(self) -> None:
        self.test_dir: Path = Path(tempfile.mkdtemp(prefix="flux_test_"))
        self.server: FluxServer = FluxServer(ServerConfig())
        self.results: list[TestResult] = []
        self.mcp_handler = self.server._register_handlers()
        
    async def setup(self) -> None:
        # Create test files
        self.small_file: Path = self.test_dir / "small.txt"
        self.small_file.write_text("Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n")
        
        self.medium_file: Path = self.test_dir / "medium.txt"
        medium_content: str = "\n".join([f"Line {i}" for i in range(1, 1001)])
        self.medium_file.write_text(medium_content)
        
        # Create large file (>10MB for memory mapping)
        self.large_file: Path = self.test_dir / "large.txt"
        large_content: str = "\n".join([f"Line {i} " + "x" * 1000 for i in range(1, 15000)])
        self.large_file.write_text(large_content)
        
        # Create file with special encoding
        self.utf16_file: Path = self.test_dir / "utf16.txt"
        self.utf16_file.write_text("Hello 世界", encoding="utf-16")
        
    async def cleanup(self) -> None:
        import shutil
        shutil.rmtree(self.test_dir)
    
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        # Call the tool handler directly
        handler = None
        
        # Find the handler registered with the decorator
        for attr_name in dir(self.server):
            attr = getattr(self.server, attr_name)
            if hasattr(attr, "__wrapped__") and hasattr(attr.__wrapped__, "__name__") and attr.__wrapped__.__name__ == "handle_tool_call":
                handler = attr.__wrapped__
                break
        
        if not handler:
            # Call through the engine directly
            if name == "flux_read_file":
                result = await self.server.engine.read_file(**arguments)
                return [type('TextContent', (), {'text': result})]
            elif name == "flux_write_file":
                result = await self.server.engine.write_file(**arguments)
                return [type('TextContent', (), {'text': result})]
            elif name == "flux_search":
                result = await self.server.engine.search(**arguments)
                return [type('TextContent', (), {'text': str(result)})]
            elif name == "flux_replace":
                result = await self.server.engine.replace(**arguments)
                return [type('TextContent', (), {'text': result})]
        
        return await handler(name, arguments)
    
    async def test_read_file_basic(self) -> TestResult:
        start_time: float = time.time()
        try:
            # Test basic read
            result = await self.call_tool(
                "flux_read_file", 
                {"path": str(self.small_file)}
            )
            
            content: str = result[0].text
            assert content == "Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n"
            
            # Test partial read
            result = await self.call_tool(
                "flux_read_file",
                {"path": str(self.small_file), "start_line": 1, "end_line": 3}
            )
            
            partial_content: str = result[0].text
            assert "Line 2" in partial_content
            assert "Line 3" in partial_content
            assert "Line 4" in partial_content
            assert "Line 5" not in partial_content
            
            return TestResult(
                test_name="Read File Basic",
                passed=True,
                duration=time.time() - start_time
            )
        except Exception as e:
            return TestResult(
                test_name="Read File Basic",
                passed=False,
                duration=time.time() - start_time,
                error=str(e)
            )
    
    async def test_write_file_atomic(self) -> TestResult:
        start_time: float = time.time()
        try:
            test_file: Path = self.test_dir / "write_test.txt"
            
            # Write file
            result = await self.call_tool(
                "flux_write_file",
                {
                    "path": str(test_file),
                    "content": "Hello\nWorld\n",
                    "create_dirs": True
                }
            )
            
            assert "Successfully wrote" in result[0].text
            assert test_file.exists()
            
            # Verify content
            content: str = test_file.read_text()
            assert content == "Hello\nWorld\n"
            
            return TestResult(
                test_name="Write File Atomic",
                passed=True,
                duration=time.time() - start_time
            )
        except Exception as e:
            return TestResult(
                test_name="Write File Atomic",
                passed=False,
                duration=time.time() - start_time,
                error=str(e)
            )
    
    async def test_search_plain_text(self) -> TestResult:
        start_time: float = time.time()
        try:
            # Search in medium file
            result = await self.call_tool(
                "flux_search",
                {
                    "path": str(self.medium_file),
                    "pattern": "Line 42",
                    "is_regex": False
                }
            )
            
            import json
            matches: list[dict[str, Any]] = json.loads(result[0].text.replace("'", '"'))
            assert len(matches) == 1
            assert matches[0]["match_text"] == "Line 42"
            assert matches[0]["line_number"] == 41  # 0-indexed
            
            return TestResult(
                test_name="Search Plain Text",
                passed=True,
                duration=time.time() - start_time
            )
        except Exception as e:
            return TestResult(
                test_name="Search Plain Text",
                passed=False,
                duration=time.time() - start_time,
                error=str(e)
            )
    
    async def test_replace_text(self) -> TestResult:
        start_time: float = time.time()
        try:
            test_file: Path = self.test_dir / "replace_test.txt"
            test_file.write_text("Hello World\nHello Universe\nGoodbye World\n")
            
            # Replace all occurrences
            result = await self.call_tool(
                "flux_replace",
                {
                    "path": str(test_file),
                    "old_text": "Hello",
                    "new_text": "Hi",
                    "is_regex": False,
                    "all_occurrences": True
                }
            )
            
            assert "Replaced 2 occurrences" in result[0].text
            
            # Verify content
            content: str = test_file.read_text()
            assert content == "Hi World\nHi Universe\nGoodbye World\n"
            
            return TestResult(
                test_name="Replace Text",
                passed=True,
                duration=time.time() - start_time
            )
        except Exception as e:
            return TestResult(
                test_name="Replace Text",
                passed=False,
                duration=time.time() - start_time,
                error=str(e)
            )
    
    async def run_all_tests(self) -> None:
        await self.setup()
        
        tests: list[tuple[str, callable]] = [
            ("Basic Read", self.test_read_file_basic),
            ("Atomic Write", self.test_write_file_atomic),
            ("Plain Text Search", self.test_search_plain_text),
            ("Text Replace", self.test_replace_text),
        ]
        
        print("FLUX MCP Integration Tests")
        print("=" * 50)
        
        for test_name, test_func in tests:
            print(f"\nRunning: {test_name}")
            result: TestResult = await test_func()
            self.results.append(result)
            
            if result.passed:
                print(f"✓ PASSED in {result.duration:.3f}s")
                if result.details:
                    for key, value in result.details.items():
                        print(f"  {key}: {value}")
            else:
                print(f"✗ FAILED in {result.duration:.3f}s")
                print(f"  Error: {result.error}")
        
        await self.cleanup()
        
        # Summary
        print("\n" + "=" * 50)
        print("Test Summary")
        print("=" * 50)
        
        passed: int = sum(1 for r in self.results if r.passed)
        failed: int = len(self.results) - passed
        
        print(f"Total Tests: {len(self.results)}")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")


if __name__ == "__main__":
    tester: FluxMCPTester = FluxMCPTester()
    asyncio.run(tester.run_all_tests())
