from __future__ import annotations

import re
import asyncio
from pathlib import Path
from typing import Any
from dataclasses import dataclass

from flux_mcp.core.memory_manager import MemoryManager
from flux_mcp.core.metal_accelerator import MetalAccelerator, CompiledPattern


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


class SearchEngine:
    def __init__(self, memory_manager: MemoryManager, gpu_enabled: bool = True) -> None:
        self.memory_manager: MemoryManager = memory_manager
        self.gpu_enabled: bool = gpu_enabled
        self.metal_accelerator: MetalAccelerator | None = None
        
        if gpu_enabled:
            try:
                self.metal_accelerator = MetalAccelerator()
            except Exception:
                self.gpu_enabled = False

    async def search(self, file_path: Path, pattern: str, is_regex: bool = False,
                    case_sensitive: bool = True, whole_word: bool = False) -> list[dict[str, Any]]:
        # Prepare pattern
        search_pattern: str = pattern
        
        if whole_word and not is_regex:
            search_pattern = rf'\b{re.escape(pattern)}\b'
            is_regex = True
        
        if not case_sensitive and not is_regex:
            search_pattern = pattern.lower()
        
        # Compile pattern if GPU is available
        compiled_pattern: CompiledPattern | None = None
        if self.metal_accelerator and self._should_use_gpu(file_path, pattern, is_regex):
            compiled_pattern = self.metal_accelerator.compile_pattern(search_pattern, is_regex)
        
        # Read file
        content: str = await self._read_file(file_path)
        
        # Perform search
        if compiled_pattern and compiled_pattern.metal_function:
            matches: list[int] = self.metal_accelerator.search_gpu(
                content.encode('utf-8'), compiled_pattern
            )
            results: list[SearchResult] = await self._process_gpu_matches(
                content, matches, pattern
            )
        else:
            results = await self._search_cpu(
                content, search_pattern, is_regex, case_sensitive
            )
        
        # Convert to dict format
        return [self._result_to_dict(result) for result in results]

    def _should_use_gpu(self, file_path: Path, pattern: str, is_regex: bool) -> bool:
        # Heuristics for GPU usage
        file_size: int = file_path.stat().st_size
        pattern_complexity: int = len(pattern)
        
        # Use GPU for large files with simple patterns
        if file_size > 1024 * 1024 and not is_regex:  # > 1MB
            return True
        
        # Use GPU for very large files regardless
        if file_size > 10 * 1024 * 1024:  # > 10MB
            return True
        
        return False

    async def _read_file(self, file_path: Path) -> str:
        if file_path.stat().st_size > self.memory_manager.config.memory_mapped_threshold:
            return await self.memory_manager.read_mapped_file(file_path)
        else:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()

    async def _search_cpu(self, content: str, pattern: str, is_regex: bool,
                         case_sensitive: bool) -> list[SearchResult]:
        results: list[SearchResult] = []
        lines: list[str] = content.splitlines()
        
        # Prepare regex
        if is_regex:
            flags: int = 0 if case_sensitive else re.IGNORECASE
            regex: re.Pattern = re.compile(pattern, flags)
        
        # Search line by line
        byte_offset: int = 0
        
        for line_num, line in enumerate(lines):
            matches: list[Any] = []
            
            if is_regex:
                matches = list(regex.finditer(line))
            else:
                if not case_sensitive:
                    search_line: str = line.lower()
                    search_pattern: str = pattern.lower()
                else:
                    search_line = line
                    search_pattern = pattern
                
                start: int = 0
                while True:
                    pos: int = search_line.find(search_pattern, start)
                    if pos == -1:
                        break
                    
                    # Create a proper match object
                    match = MatchObject(
                        start_pos=pos,
                        end_pos=pos + len(search_pattern),
                        text=line[pos:pos + len(search_pattern)]
                    )
                    matches.append(match)
                    start = pos + 1
            
            for match in matches:
                # Get context
                match_start: int = match.start()
                match_end: int = match.end()
                
                context_before: str = line[:match_start][-50:]
                context_after: str = line[match_end:][:50]
                
                result: SearchResult = SearchResult(
                    line_number=line_num,
                    column=match_start,
                    match_text=match.group(),
                    context_before=context_before,
                    context_after=context_after,
                    byte_offset=byte_offset + match_start
                )
                results.append(result)
            
            byte_offset += len(line) + 1  # +1 for newline
        
        return results

    async def _process_gpu_matches(self, content: str, match_positions: list[int],
                                  pattern: str) -> list[SearchResult]:
        results: list[SearchResult] = []
        lines: list[str] = content.splitlines()
        
        # Build line offset index
        line_offsets: list[int] = [0]
        current_offset: int = 0
        
        for line in lines:
            current_offset += len(line) + 1
            line_offsets.append(current_offset)
        
        # Process each match
        for pos in match_positions:
            # Find line number
            line_num: int = 0
            for i, offset in enumerate(line_offsets):
                if offset > pos:
                    line_num = i - 1
                    break
            
            # Calculate column
            line_start: int = line_offsets[line_num]
            column: int = pos - line_start
            
            # Get match text
            match_text: str = content[pos:pos + len(pattern)]
            
            # Get context
            line: str = lines[line_num]
            context_before: str = line[:column][-50:]
            context_after: str = line[column + len(pattern):][:50]
            
            result: SearchResult = SearchResult(
                line_number=line_num,
                column=column,
                match_text=match_text,
                context_before=context_before,
                context_after=context_after,
                byte_offset=pos
            )
            results.append(result)
        
        return results

    def _result_to_dict(self, result: SearchResult) -> dict[str, Any]:
        return {
            'line_number': result.line_number,
            'column': result.column,
            'match_text': result.match_text,
            'context_before': result.context_before,
            'context_after': result.context_after,
            'byte_offset': result.byte_offset
        }

    async def search_multiple_files(self, file_paths: list[Path], pattern: str,
                                   is_regex: bool = False, case_sensitive: bool = True,
                                   whole_word: bool = False) -> dict[str, list[dict[str, Any]]]:
        tasks: list[asyncio.Task] = []
        
        for file_path in file_paths:
            task: asyncio.Task = asyncio.create_task(
                self.search(file_path, pattern, is_regex, case_sensitive, whole_word)
            )
            tasks.append(task)
        
        results: list[list[dict[str, Any]]] = await asyncio.gather(*tasks)
        
        return {
            str(file_path): result
            for file_path, result in zip(file_paths, results)
        }

    def close(self) -> None:
        if self.metal_accelerator:
            self.metal_accelerator.cleanup()
