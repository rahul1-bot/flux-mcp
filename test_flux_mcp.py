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
    
    async def test_read_file_basic(self) -> TestResult:
        start_time: float = time.time()
        try:
            # Test basic read
            result: list[Any] = await self.server.handle_tool_call(
                "flux_read_file", 
                {"path": str(self.small_file)}
            )
            
            content: str = result[0].text
            assert content == "Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n"
            
            # Test partial read
            result = await self.server.handle_tool_call(
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
    
    async def test_read_large_file(self) -> TestResult:
        start_time: float = time.time()
        try:
            # This should trigger memory mapping
            result: list[Any] = await self.server.handle_tool_call(
                "flux_read_file",
                {"path": str(self.large_file), "start_line": 0, "end_line": 10}
            )
            
            content: str = result[0].text
            assert "Line 1" in content
            assert "Line 10" in content
            
            # Measure performance
            read_time: float = time.time() - start_time
            
            return TestResult(
                test_name="Read Large File (Memory Mapped)",
                passed=True,
                duration=read_time,
                details={"file_size_mb": self.large_file.stat().st_size / (1024*1024)}
            )
        except Exception as e:
            return TestResult(
                test_name="Read Large File (Memory Mapped)",
                passed=False,
                duration=time.time() - start_time,
                error=str(e)
            )
    
    async def test_encoding_detection(self) -> TestResult:
        start_time: float = time.time()
        try:
            # Test auto encoding detection
            result: list[Any] = await self.server.handle_tool_call(
                "flux_read_file",
                {"path": str(self.utf16_file)}
            )
            
            content: str = result[0].text
            assert "Hello 世界" in content
            
            return TestResult(
                test_name="Encoding Detection",
                passed=True,
                duration=time.time() - start_time
            )
        except Exception as e:
            return TestResult(
                test_name="Encoding Detection",
                passed=False,
                duration=time.time() - start_time,
                error=str(e)
            )
    
    async def test_write_file_atomic(self) -> TestResult:
        start_time: float = time.time()
        try:
            test_file: Path = self.test_dir / "write_test.txt"
            
            # Write file
            result: list[Any] = await self.server.handle_tool_call(
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
            result: list[Any] = await self.server.handle_tool_call(
                "flux_search",
                {
                    "path": str(self.medium_file),
                    "pattern": "Line 42",
                    "is_regex": False
                }
            )
            
            matches: list[dict[str, Any]] = eval(result[0].text)
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
    
    async def test_search_regex(self) -> TestResult:
        start_time: float = time.time()
        try:
            # Search with regex
            result: list[Any] = await self.server.handle_tool_call(
                "flux_search",
                {
                    "path": str(self.medium_file),
                    "pattern": r"Line \d{2}$",
                    "is_regex": True
                }
            )
            
            matches: list[dict[str, Any]] = eval(result[0].text)
            # Should match Line 10-99 (90 matches)
            assert len(matches) == 90
            
            return TestResult(
                test_name="Search Regex",
                passed=True,
                duration=time.time() - start_time,
                details={"matches_found": len(matches)}
            )
        except Exception as e:
            return TestResult(
                test_name="Search Regex",
                passed=False,
                duration=time.time() - start_time,
                error=str(e)
            )
    
    async def test_search_large_file_gpu(self) -> TestResult:
        start_time: float = time.time()
        try:
            # This should trigger GPU acceleration
            result: list[Any] = await self.server.handle_tool_call(
                "flux_search",
                {
                    "path": str(self.large_file),
                    "pattern": "Line 5000",
                    "is_regex": False
                }
            )
            
            matches: list[dict[str, Any]] = eval(result[0].text)
            assert len(matches) >= 1
            
            search_time: float = time.time() - start_time
            
            return TestResult(
                test_name="Search Large File (GPU)",
                passed=True,
                duration=search_time,
                details={
                    "file_size_mb": self.large_file.stat().st_size / (1024*1024),
                    "search_time_ms": search_time * 1000
                }
            )
        except Exception as e:
            return TestResult(
                test_name="Search Large File (GPU)",
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
            result: list[Any] = await self.server.handle_tool_call(
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
    
    async def test_transaction_rollback(self) -> TestResult:
        start_time: float = time.time()
        try:
            test_file: Path = self.test_dir / "transaction_test.txt"
            original_content: str = "Original Content\n"
            test_file.write_text(original_content)
            
            # Simulate a failed write by causing an exception
            # This should trigger rollback
            try:
                # Create a read-only file to cause write failure
                test_file.chmod(0o444)
                
                await self.server.handle_tool_call(
                    "flux_write_file",
                    {
                        "path": str(test_file),
                        "content": "New Content\n"
                    }
                )
                
                # Should not reach here
                assert False, "Write should have failed"
                
            except Exception:
                # Expected failure
                pass
            finally:
                # Restore permissions
                test_file.chmod(0o644)
            
            # Verify original content is preserved
            content: str = test_file.read_text()
            assert content == original_content
            
            return TestResult(
                test_name="Transaction Rollback",
                passed=True,
                duration=time.time() - start_time
            )
        except Exception as e:
            return TestResult(
                test_name="Transaction Rollback",
                passed=False,
                duration=time.time() - start_time,
                error=str(e)
            )
    
    async def test_concurrent_operations(self) -> TestResult:
        start_time: float = time.time()
        try:
            # Test concurrent reads
            tasks: list[asyncio.Task] = []
            
            for i in range(10):
                task: asyncio.Task = asyncio.create_task(
                    self.server.handle_tool_call(
                        "flux_read_file",
                        {"path": str(self.medium_file), "start_line": i*10, "end_line": (i+1)*10}
                    )
                )
                tasks.append(task)
            
            results: list[list[Any]] = await asyncio.gather(*tasks)
            
            # All reads should succeed
            for i, result in enumerate(results):
                content: str = result[0].text
                assert f"Line {i*10 + 1}" in content
            
            return TestResult(
                test_name="Concurrent Operations",
                passed=True,
                duration=time.time() - start_time,
                details={"concurrent_tasks": len(tasks)}
            )
        except Exception as e:
            return TestResult(
                test_name="Concurrent Operations",
                passed=False,
                duration=time.time() - start_time,
                error=str(e)
            )
    
    async def run_all_tests(self) -> None:
        await self.setup()
        
        tests: list[tuple[str, callable]] = [
            ("Basic Read", self.test_read_file_basic),
            ("Large File Read", self.test_read_large_file),
            ("Encoding Detection", self.test_encoding_detection),
            ("Atomic Write", self.test_write_file_atomic),
            ("Plain Text Search", self.test_search_plain_text),
            ("Regex Search", self.test_search_regex),
            ("Large File GPU Search", self.test_search_large_file_gpu),
            ("Text Replace", self.test_replace_text),
            ("Transaction Rollback", self.test_transaction_rollback),
            ("Concurrent Operations", self.test_concurrent_operations)
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
        
        # Performance Summary
        print("\nPerformance Highlights:")
        for result in self.results:
            if result.passed and result.details:
                print(f"- {result.test_name}: {result.duration:.3f}s")
                for key, value in result.details.items():
                    print(f"    {key}: {value}")


async def benchmark_performance() -> None:
    print("\nPerformance Benchmarks")
    print("=" * 50)
    
    temp_dir: Path = Path(tempfile.mkdtemp(prefix="flux_bench_"))
    server: FluxServer = FluxServer(ServerConfig())
    
    # Create test files of various sizes
    sizes: list[tuple[str, int]] = [
        ("1KB", 1024),
        ("10KB", 10 * 1024),
        ("100KB", 100 * 1024),
        ("1MB", 1024 * 1024),
        ("10MB", 10 * 1024 * 1024),
        ("100MB", 100 * 1024 * 1024)
    ]
    
    for size_name, size_bytes in sizes:
        file_path: Path = temp_dir / f"test_{size_name}.txt"
        
        # Create file with random content
        content: str = "x" * (size_bytes // 2) + "\n" + "y" * (size_bytes // 2)
        file_path.write_text(content)
        
        print(f"\n{size_name} File Operations:")
        
        # Benchmark read
        start_time: float = time.time()
        await server.handle_tool_call("flux_read_file", {"path": str(file_path)})
        read_time: float = time.time() - start_time
        print(f"  Read: {read_time:.4f}s ({size_bytes/read_time/1024/1024:.1f} MB/s)")
        
        # Benchmark search
        start_time = time.time()
        await server.handle_tool_call(
            "flux_search",
            {"path": str(file_path), "pattern": "xxx", "is_regex": False}
        )
        search_time: float = time.time() - start_time
        print(f"  Search: {search_time:.4f}s ({size_bytes/search_time/1024/1024:.1f} MB/s)")
        
        # Benchmark replace
        start_time = time.time()
        await server.handle_tool_call(
            "flux_replace",
            {
                "path": str(file_path),
                "old_text": "xxx",
                "new_text": "zzz",
                "is_regex": False,
                "all_occurrences": True
            }
        )
        replace_time: float = time.time() - start_time
        print(f"  Replace: {replace_time:.4f}s")
    
    # Cleanup
    import shutil
    shutil.rmtree(temp_dir)


if __name__ == "__main__":
    tester: FluxMCPTester = FluxMCPTester()
    
    # Run integration tests
    asyncio.run(tester.run_all_tests())
    
    # Run performance benchmarks
    asyncio.run(benchmark_performance())
