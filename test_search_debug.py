from __future__ import annotations

import asyncio
import tempfile
import time
import os
from pathlib import Path
from typing import Any
from dataclasses import dataclass
import traceback

from flux_mcp.server import FluxServer, ServerConfig
from flux_mcp.core.transaction_manager import TransactionManager
from flux_mcp.operations.file_handler import FileHandler
from flux_mcp.operations.text_editor import TextEditor
from flux_mcp.operations.search_engine import SearchEngine


@dataclass
class TestResult:
    test_name: str
    passed: bool
    duration: float
    error: str | None = None
    details: dict[str, Any] | None = None


class DirectFluxTester:
    def __init__(self) -> None:
        self.test_dir: Path = Path(tempfile.mkdtemp(prefix="flux_test_"))
        config: ServerConfig = ServerConfig()
        
        # Create components directly
        self.transaction_manager: TransactionManager = TransactionManager()
        from flux_mcp.core.memory_manager import MemoryManager
        self.memory_manager: MemoryManager = MemoryManager(config)
        self.file_handler: FileHandler = FileHandler(self.transaction_manager, self.memory_manager)
        self.text_editor: TextEditor = TextEditor(self.transaction_manager, self.memory_manager)
        self.search_engine: SearchEngine = SearchEngine(self.memory_manager, config.gpu_enabled)
        
        self.results: list[TestResult] = []
        
    async def setup(self) -> None:
        # Create test files
        self.small_file: Path = self.test_dir / "small.txt"
        self.small_file.write_text("Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n")
        
        self.medium_file: Path = self.test_dir / "medium.txt"
        medium_content: str = "\n".join([f"Line {i}" for i in range(1, 1001)])
        self.medium_file.write_text(medium_content)
        
    async def cleanup(self) -> None:
        import shutil
        shutil.rmtree(self.test_dir)
    
    async def test_search_plain_text(self) -> TestResult:
        start_time: float = time.time()
        try:
            # Debug: Let's see what's in the file
            content: str = self.medium_file.read_text()
            lines: list[str] = content.splitlines()
            print(f"Debug: Total lines: {len(lines)}")
            print(f"Debug: Line 42: {lines[41] if len(lines) > 41 else 'NOT FOUND'}")
            
            # Search in medium file
            results: list[dict[str, Any]] = await self.search_engine.search(
                self.medium_file,
                "Line 42",
                is_regex=False,
                case_sensitive=True,
                whole_word=False
            )
            
            print(f"Debug: Search results: {results}")
            
            assert len(results) == 1, f"Expected 1 result, got {len(results)}"
            assert results[0]["match_text"] == "Line 42"
            assert results[0]["line_number"] == 41  # 0-indexed
            
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
                error=f"{str(e)}\n{traceback.format_exc()}"
            )
    
    async def run_all_tests(self) -> None:
        await self.setup()
        
        tests: list[tuple[str, callable]] = [
            ("Plain Text Search", self.test_search_plain_text),
        ]
        
        print("FLUX Direct Component Tests")
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
    tester: DirectFluxTester = DirectFluxTester()
    asyncio.run(tester.run_all_tests())
