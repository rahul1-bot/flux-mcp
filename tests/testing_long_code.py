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







class FluxEngine:
    def __init__(self, config: EngineConfig) -> None:
        self.config: EngineConfig = config
        self.transaction_manager: TransactionManager = TransactionManager()
        self.memory_manager: MemoryManager = MemoryManager(config)
        self.file_handler: FileHandler = FileHandler(self.transaction_manager, self.memory_manager)
        self.text_editor: TextEditor = TextEditor(self.transaction_manager, self.memory_manager)
        self.search_engine: SearchEngine = SearchEngine(self.memory_manager, config.gpu_enabled)
        self.version_control: VersionControl = VersionControl()
        self.executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=config.worker_count)

    async def read_file(self, path: str, encoding: str | None = None, 
                       start_line: int | None = None, end_line: int | None = None) -> str:
        file_path: Path = Path(path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        # Skip memory mapping for small files or partial reads
        file_size: int = file_path.stat().st_size
        use_mmap: bool = (
            file_size > self.config.memory_mapped_threshold and 
            start_line is None and 
            end_line is None
        )
        
        if use_mmap:
            return await self.memory_manager.read_mapped_file(
                file_path, encoding, start_line, end_line
            )
        else:
            return await self.file_handler.read_file(
                file_path, encoding, start_line, end_line
            )

    async def write_file(self, path: str, content: str, 
                        encoding: str = "utf-8", create_dirs: bool = True,
                        simple_mode: bool = False) -> str:
        file_path: Path = Path(path)
        
        if create_dirs and not file_path.parent.exists():
            file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Simple mode for small files - skip transactions
        if simple_mode or len(content) < 10000:  # < 10KB
            # Direct write without transaction overhead
            file_path.write_text(content, encoding=encoding)
            return f"Successfully wrote to {path}"
        
        # Full transaction mode for larger files
        transaction_id: str = await self.transaction_manager.begin()
        
        try:
            await self.file_handler.write_file(file_path, content, encoding)
            await self.transaction_manager.commit(transaction_id)
            return f"Successfully wrote to {path}"
        except Exception as e:
            await self.transaction_manager.rollback(transaction_id)
            raise Exception(f"Failed to write file: {e}")

    async def search(self, path: str, pattern: str, is_regex: bool = False, 
                    case_sensitive: bool = True, whole_word: bool = False,
                    simple_mode: bool = False) -> list[dict[str, Any]]:
        file_path: Path = Path(path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        # Simple mode for small files and simple patterns
        if simple_mode or (file_path.stat().st_size < 100000 and not is_regex):
            # Fast path for simple searches
            content: str = file_path.read_text()
            results: list[dict[str, Any]] = []
            
            search_pattern: str = pattern if case_sensitive else pattern.lower()
            search_content: str = content if case_sensitive else content.lower()
            
            lines: list[str] = search_content.splitlines()
            for line_num, line in enumerate(lines):
                if search_pattern in line:
                    column: int = line.find(search_pattern)
                    results.append({
                        'line_number': line_num,
                        'column': column,
                        'match_text': pattern,
                        'context_before': line[:column][-50:],
                        'context_after': line[column + len(pattern):][:50],
                        'byte_offset': sum(len(l) + 1 for l in lines[:line_num]) + column
                    })
            
            return results
        
        # Full search engine for complex cases
        return await self.search_engine.search(
            file_path, pattern, is_regex, case_sensitive, whole_word
        )

    async def replace(self, path: str, old_text: str, new_text: str, 
                     is_regex: bool = False, all_occurrences: bool = True,
                     simple_mode: bool = False) -> str:
        file_path: Path = Path(path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        # Auto-detect simple mode
        file_size: int = file_path.stat().st_size
        is_simple: bool = (
            simple_mode or 
            (file_size < 1000000 and not is_regex and len(old_text) < 1000)
        )
        
        if is_simple:
            # Fast path for simple replacements
            content: str = file_path.read_text()
            
            if all_occurrences:
                new_content: str = content.replace(old_text, new_text)
                count: int = content.count(old_text)
            else:
                new_content = content.replace(old_text, new_text, 1)
                count = 1 if old_text in content else 0
            
            # Direct write for simple mode
            file_path.write_text(new_content)
            return f"Replaced {count} occurrences in {path}"
        
        # Full transaction mode for complex replacements
        transaction_id: str = await self.transaction_manager.begin()
        
        


@dataclass
class SearchResult:
    line_number: int
    column: int
    match_text: str
    context_before: str
    context_after: str
    byte_offset: int


class MatchObject:
    def __init__(self, start_pos: int, end_pos: int, text: str) -> None:
        self._start: int = start_pos
        self._end: int = end_pos
        self._text: str = text
    
    def start(self) -> int:
        return self._start
    
    def end(self) -> int:
        return self._end
    
    def group(self) -> str:
        return self._text


class AdvancedSearchEngine:
    def __init__(self, memory_manager: MemoryManager, gpu_enabled: bool = True) -> None:
        self.memory_manager: MemoryManager = memory_manager
        self.gpu_enabled: bool = gpu_enabled
        self.metal_accelerator: MetalAccelerator | None = None
        self.cache: dict[str, Any] = {}
        self.last_results: list[dict[str, Any]] = []
        self.optimization_level: int = 3
        self.advanced_features_enabled: bool = True
        self.search_history: list[str] = []
        
        if gpu_enabled:
            try:
                self.metal_accelerator = MetalAccelerator()
                # Initialize advanced features
                self.advanced_features_enabled = True
                self.optimization_level = 5  # Maximum optimization
            except Exception:
                self.gpu_enabled = False
                self.advanced_features_enabled = Falseclass FluxMCPTester:
    def __init__(self) -> None:
        self.test_dir: Path = Path(tempfile.mkdtemp(prefix="flux_test_"))
        self.server: FluxServer = FluxServer(ServerConfig())
        self.results: list[TestResult] = []
        
    async def setup(self) -> None:
        print("Setting up enhanced test environment")
        
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
        
        # Create additional test files for advanced testing
        self.json_file: Path = self.test_dir / "test.json"
        self.json_file.write_text('{"name": "test", "values": [1, 2, 3]}')
        
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




def test_addition_function() -> None:
    print("Testing enhanced function")
    
    # Create a complex nested data structure
    test_data: dict[str, Any] = {
        "name": "TestData",
        "values": [1, 2, 3, 4, 5],
        "nested": {
            "level1": {
                "level2": {
                    "level3": "deep value"
                }
            }
        },
        "functions": [
            lambda x: x * 2,
            lambda y: y + 10
        ]
    }
    
    # Process the data with both functions
    processed1: list[int] = []
    processed2: list[int] = []
    
    for item in test_data["values"]:
        processed1.append(test_data["functions"][0](item))
        processed2.append(test_data["functions"][1](item))
    
    print(f"First transformation: {processed1}")
    print(f"Second transformation: {processed2}")
    
    # Add recursive dictionary explorer
    def explore_dict(data: dict[str, Any], path: str = "") -> None:
        for key, value in data.items():
            current_path: str = f"{path}.{key}" if path else key
            
            if isinstance(value, dict):
                print(f"Dict at: {current_path}")
                explore_dict(value, current_path)
            else:
                print(f"{current_path}: {value}")
    
    print("\nExploring nested structure:")
    explore_dict(test_data)
    print("Test function completed successfully")if __name__ == "__main__":
    print("Starting tests...")
    print("MAIN CODE IS WORKING")
    test_addition_function()