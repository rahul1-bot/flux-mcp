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
        # Create content with distinct patterns to avoid overlaps
        medium_content: str = "\n".join([f"Line {i:04d}" for i in range(1, 1001)])
        self.medium_file.write_text(medium_content)
        
        # Create large file (>10MB for memory mapping)
        self.large_file: Path = self.test_dir / "large.txt"
        large_content: str = "\n".join([f"Line {i:05d} " + "x" * 1000 for i in range(1, 15000)])
        self.large_file.write_text(large_content)
        
    async def cleanup(self) -> None:
        import shutil
        shutil.rmtree(self.test_dir)
    
    async def test_read_file_basic(self) -> TestResult:
        start_time: float = time.time()
        try:
            # Test basic read
            content: str = await self.file_handler.read_file(
                self.small_file, 
                encoding=None,
                start_line=None,
                end_line=None
            )
            
            assert content == "Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n"
            
            # Test partial read
            partial_content: str = await self.file_handler.read_file(
                self.small_file,
                encoding=None,
                start_line=1,
                end_line=3
            )
            
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
                error=f"{str(e)}\n{traceback.format_exc()}"
            )
    
    async def test_write_file_atomic(self) -> TestResult:
        start_time: float = time.time()
        try:
            test_file: Path = self.test_dir / "subdir" / "write_test.txt"
            
            # Make sure parent directory doesn't exist yet
            assert not test_file.parent.exists()
            
            # Create parent directory
            test_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Write file
            await self.file_handler.write_file(
                test_file,
                "Hello\nWorld\n",
                "utf-8"
            )
            
            # Commit the transaction
            transaction_id: str = list(self.transaction_manager.transactions.keys())[0]
            await self.transaction_manager.commit(transaction_id)
            
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
                error=f"{str(e)}\n{traceback.format_exc()}"
            )
    
    async def test_search_plain_text(self) -> TestResult:
        start_time: float = time.time()
        try:
            # Search in medium file for a unique pattern
            results: list[dict[str, Any]] = await self.search_engine.search(
                self.medium_file,
                "Line 0042",  # This should be unique
                is_regex=False,
                case_sensitive=True,
                whole_word=False
            )
            
            assert len(results) == 1, f"Expected 1 result, got {len(results)}"
            assert results[0]["match_text"] == "Line 0042"
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
    
    async def test_search_regex(self) -> TestResult:
        start_time: float = time.time()
        try:
            # Search with regex
            results: list[dict[str, Any]] = await self.search_engine.search(
                self.medium_file,
                r"Line 00\d{2}$",  # Match Line 0000-0099
                is_regex=True,
                case_sensitive=True,
                whole_word=False
            )
            
            assert len(results) == 99, f"Expected 99 results, got {len(results)}"
            
            return TestResult(
                test_name="Search Regex",
                passed=True,
                duration=time.time() - start_time,
                details={"matches_found": len(results)}
            )
        except Exception as e:
            return TestResult(
                test_name="Search Regex",
                passed=False,
                duration=time.time() - start_time,
                error=f"{str(e)}\n{traceback.format_exc()}"
            )
    
    async def test_replace_text(self) -> TestResult:
        start_time: float = time.time()
        try:
            test_file: Path = self.test_dir / "replace_test.txt"
            test_file.write_text("Hello World\nHello Universe\nGoodbye World\n")
            
            # Replace all occurrences
            count: int = await self.text_editor.replace(
                test_file,
                "Hello",
                "Hi",
                is_regex=False,
                all_occurrences=True
            )
            
            assert count == 2
            
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
                error=f"{str(e)}\n{traceback.format_exc()}"
            )
    
    async def test_transaction_rollback(self) -> TestResult:
        start_time: float = time.time()
        try:
            test_file: Path = self.test_dir / "transaction_test.txt"
            original_content: str = "Original Content\n"
            test_file.write_text(original_content)
            
            # Start a transaction
            transaction_id: str = await self.transaction_manager.begin()
            
            try:
                # Acquire lock
                await self.transaction_manager.acquire_file_lock(transaction_id, test_file)
                
                # Write to temp file
                await self.transaction_manager.write_to_temp(
                    transaction_id,
                    test_file,
                    b"New Content\n"
                )
                
                # Force an error by raising an exception
                raise Exception("Simulated error")
                
            except Exception:
                # Rollback
                await self.transaction_manager.rollback(transaction_id)
            
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
                error=f"{str(e)}\n{traceback.format_exc()}"
            )
    
    async def test_memory_mapping(self) -> TestResult:
        start_time: float = time.time()
        try:
            # Create a large file (>10MB)
            large_file: Path = self.test_dir / "large.txt"
            content: str = "x" * (15 * 1024 * 1024)  # 15MB
            large_file.write_text(content)
            
            # This should trigger memory mapping
            mapped_content: str = await self.memory_manager.read_mapped_file(
                large_file,
                encoding="utf-8"
            )
            
            assert len(mapped_content) == len(content)
            assert mapped_content[:100] == content[:100]
            
            return TestResult(
                test_name="Memory Mapping",
                passed=True,
                duration=time.time() - start_time,
                details={"file_size_mb": len(content) / (1024*1024)}
            )
        except Exception as e:
            return TestResult(
                test_name="Memory Mapping",
                passed=False,
                duration=time.time() - start_time,
                error=f"{str(e)}\n{traceback.format_exc()}"
            )
    
    async def test_search_large_file_gpu(self) -> TestResult:
        start_time: float = time.time()
        try:
            # This should trigger GPU acceleration
            results: list[dict[str, Any]] = await self.search_engine.search(
                self.large_file,
                "Line 05000",
                is_regex=False,
                case_sensitive=True,
                whole_word=False
            )
            
            assert len(results) >= 1
            
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
                error=f"{str(e)}\n{traceback.format_exc()}"
            )
    
    async def run_all_tests(self) -> None:
        await self.setup()
        
        tests: list[tuple[str, callable]] = [
            ("Basic Read", self.test_read_file_basic),
            ("Atomic Write", self.test_write_file_atomic),
            ("Plain Text Search", self.test_search_plain_text),
            ("Regex Search", self.test_search_regex),
            ("Text Replace", self.test_replace_text),
            ("Transaction Rollback", self.test_transaction_rollback),
            ("Memory Mapping", self.test_memory_mapping),
            ("Large File GPU Search", self.test_search_large_file_gpu),
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
        
        # Performance Summary
        print("\nPerformance Highlights:")
        for result in self.results:
            if result.passed and result.details:
                print(f"- {result.test_name}: {result.duration:.3f}s")
                for key, value in result.details.items():
                    print(f"    {key}: {value}")


if __name__ == "__main__":
    tester: DirectFluxTester = DirectFluxTester()
    asyncio.run(tester.run_all_tests())
