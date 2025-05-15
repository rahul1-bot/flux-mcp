from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from flux_mcp.core.transaction_manager import TransactionManager
from flux_mcp.core.memory_manager import MemoryManager
from flux_mcp.operations.file_handler import FileHandler
from flux_mcp.operations.text_editor import TextEditor
from flux_mcp.operations.search_engine import SearchEngine
from flux_mcp.operations.version_control import VersionControl


@dataclass
class EngineConfig:
    memory_mapped_threshold: int
    chunk_size: int
    worker_count: int
    cache_size: int
    gpu_enabled: bool


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



    async def text_replace(self, path: str, highlight: str | dict[str, Any], 
                         replace_with: str, checkpoint: str | None = None,
                         auto_checkpoint: bool = False) -> str:
        """Advanced text replacement with hierarchical selection.
        
        Args:
            path: File path to modify
            highlight: Target specification in format "ClassName" or "ClassName.method_name"
                   DO NOT include 'class' or 'def' keywords, parentheses, or colons
            replace_with: Replacement text (triple quotes recommended)
            checkpoint: Optional name for the checkpoint
            auto_checkpoint: Whether to auto-generate a checkpoint name
        
        Returns:
            Success message
        """
        try:
            file_path: Path = Path(path)
            
            if not file_path.exists():
                raise FileNotFoundError(f"File not found: {path}")
            
            try:
                result: str = await self.text_editor.text_replace(
                    file_path, highlight, replace_with, checkpoint, auto_checkpoint
                )
                return result
            except ValueError as e:
                # Provide more user-friendly error information
                if "could not find" in str(e).lower():
                    try:
                        # Safely scan the file to count major elements
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        
                        import re
                        class_count = len(re.findall(r'^\s*class\s+(\w+)', content, re.MULTILINE))
                        func_count = len(re.findall(r'^\s*def\s+(\w+)', content, re.MULTILINE))
                        
                        help_message = (
                            f"ERROR: Target not found in {path}\n\n"
                            f"CORRECT FORMAT: Use 'ClassName' or 'ClassName.method_name' format.\n"
                            f"DO NOT include 'class' or 'def' keywords, parentheses, or colons.\n\n"
                            f"EXAMPLES:\n"
                            f"  highlight='MyClass'        ✓ CORRECT\n"
                            f"  highlight='MyClass.method' ✓ CORRECT\n"
                            f"  highlight='class MyClass'  ✗ INCORRECT (don't include 'class')\n"
                            f"  highlight='def method()'   ✗ INCORRECT (don't include 'def' or parentheses)\n\n"
                            f"This file contains approximately {class_count} classes and {func_count} functions.\n\n"
                            f"ERROR DETAILS: {e}"
                        )
                    except Exception as scan_error:
                        # Fallback if we can't scan the file
                        help_message = (
                            f"ERROR: Target not found in {path}\n\n"
                            f"CORRECT FORMAT: Use 'ClassName' or 'ClassName.method_name' format.\n"
                            f"DO NOT include 'class' or 'def' keywords, parentheses, or colons.\n\n"
                            f"EXAMPLES:\n"
                            f"  highlight='MyClass'        ✓ CORRECT\n"
                            f"  highlight='MyClass.method' ✓ CORRECT\n"
                            f"  highlight='class MyClass'  ✗ INCORRECT (don't include 'class')\n"
                            f"  highlight='def method()'   ✗ INCORRECT (don't include 'def' or parentheses)\n\n"
                            f"ERROR DETAILS: {e}"
                        )
                        
                    raise Exception(help_message)
                else:
                    raise Exception(f"Failed to replace text: {e}")
            except Exception as e:
                # Create detailed error report
                error_details = str(e)
                if hasattr(e, '__traceback__'):
                    import traceback
                    error_details = f"{error_details}\n\nDetails: {traceback.format_exc()}"
                
                raise Exception(f"Failed to replace text: {error_details}")
                
        except Exception as outer_e:
            # Ultimate fallback to prevent server crashes
            try:
                error_message = str(outer_e)
                # Log the error but return a graceful message
                if hasattr(outer_e, '__traceback__'):
                    import logging
                    import traceback
                    logging.error(f"text_replace error: {traceback.format_exc()}")
                else:
                    import logging
                    logging.error(f"text_replace error: {error_message}")
                    
                return f"ERROR: {error_message}"
            except:
                # Even if logging fails, return something rather than crash
                return "ERROR: Failed to replace text. See server logs for details."

    def __del__(self) -> None:
        self.executor.shutdown(wait=True)
