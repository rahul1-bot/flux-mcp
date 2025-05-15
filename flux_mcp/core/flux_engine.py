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
                         auto_checkpoint: bool = False, dry_run: bool = False,
                         batch_mode: bool = False) -> str:
        """Advanced text replacement with hierarchical selection."""
        try:
            file_path: Path = Path(path)
            
            if not file_path.exists():
                raise FileNotFoundError(f"File not found: {path}")
            
            try:
                results: dict[str, Any] = await self.text_editor.text_replace(
                    file_path, highlight, replace_with, checkpoint, auto_checkpoint, 
                    dry_run=dry_run, batch_mode=batch_mode
                )
                
                if dry_run:
                    return results["diff_output"]
                    
                return results["message"]
                
            except ValueError as e:
                error_str: str = str(e).lower()
                
                if "could not find" in error_str:
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content: str = f.read()
                        
                        import re
                        class_count: int = len(re.findall(r'^\s*class\s+(\w+)', content, re.MULTILINE))
                        func_count: int = len(re.findall(r'^\s*def\s+(\w+)', content, re.MULTILINE))
                        
                        similar_targets: list[tuple[str, float]] = self.text_editor.find_similar_targets(
                            file_path, highlight if isinstance(highlight, str) else highlight.get("target", "")
                        )
                        
                        suggestions: str = ""
                        if similar_targets:
                            suggestions = "\n🔍 Similar targets found:"
                            for target, score in similar_targets:
                                suggestions += f"\n  → '{target}' (similarity: {score:.0%})"
                            
                            if score := similar_targets[0][1] >= 0.85:
                                suggestions += f"\n\n🔄 Try with: highlight='{similar_targets[0][0]}'"
                        
                        help_message: str = (
                            f"ERROR: Target not found in {path}\n\n"
                            f"CORRECT FORMAT: Use 'ClassName' or 'ClassName.method_name' format.\n"
                            f"DO NOT include 'class' or 'def' keywords, parentheses, or colons.\n\n"
                            f"EXAMPLES:\n"
                            f"  highlight='MyClass'        ✓ CORRECT\n"
                            f"  highlight='MyClass.method' ✓ CORRECT\n"
                            f"  highlight='class MyClass'  ✗ INCORRECT (don't include 'class')\n"
                            f"  highlight='def method()'   ✗ INCORRECT (don't include 'def' or parentheses)\n\n"
                            f"This file contains approximately {class_count} classes and {func_count} functions.\n\n"
                            f"{suggestions}\n\n"
                            f"ERROR DETAILS: {e}"
                        )
                        
                        if isinstance(highlight, str) and "." not in highlight:
                            recovery_result: dict[str, Any] | None = await self.text_editor.try_fuzzy_recovery(
                                file_path, highlight, replace_with, auto_checkpoint, 
                                threshold=0.85, dry_run=dry_run
                            )
                            
                            if recovery_result:
                                recovery_msg: str = (
                                    f"🛠️ RECOVERY SUGGESTION: Found similar target '{recovery_result['target']}'.\n\n"
                                    f"Would you like to use this target instead?\n"
                                    f"Try with: highlight='{recovery_result['target']}'"
                                )
                                return recovery_msg
                                
                    except Exception as scan_error:
                        help_message: str = (
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
                    
                elif "invalid python" in error_str or "syntax error" in error_str:
                    import re
                    error_line_match: re.Match | None = re.search(r'line (\d+)', error_str)
                    line_info: str = f"around line {error_line_match.group(1)}" if error_line_match else ""
                    
                    help_message: str = (
                        f"SYNTAX ERROR: The replacement code contains Python syntax errors {line_info}.\n\n"
                        f"ERROR DETAILS: {e}\n\n"
                        f"Try using triple quotes for multi-line code: replace_with=\"\"\"def method():\\n    ..."
                    )
                    raise Exception(help_message)
                else:
                    raise Exception(f"Failed to replace text: {e}")
            except Exception as e:
                error_details: str = str(e)
                if hasattr(e, '__traceback__'):
                    import traceback
                    error_details = f"{error_details}\n\nDetails: {traceback.format_exc()}"
                
                raise Exception(f"Failed to replace text: {error_details}")
                
        except Exception as outer_e:
            try:
                error_message: str = str(outer_e)
                if hasattr(outer_e, '__traceback__'):
                    import logging
                    import traceback
                    logging.error(f"text_replace error: {traceback.format_exc()}")
                else:
                    import logging
                    logging.error(f"text_replace error: {error_message}")
                    
                return f"ERROR: {error_message}"
            except:
                return "ERROR: Failed to replace text. See server logs for details."

    def __del__(self) -> None:
        self.executor.shutdown(wait=True)
