from __future__ import annotations

import re
import asyncio
from pathlib import Path
from typing import Any
from dataclasses import dataclass

from flux_mcp.core.transaction_manager import TransactionManager
from flux_mcp.core.memory_manager import MemoryManager


@dataclass
class EditOperation:
    line_number: int
    column: int
    old_text: str
    new_text: str
    

@dataclass
class TextRange:
    start_line: int
    start_column: int
    end_line: int
    end_column: int


class TextEditor:
    def __init__(self, transaction_manager: TransactionManager,
                 memory_manager: MemoryManager) -> None:
        self.transaction_manager: TransactionManager = transaction_manager
        self.memory_manager: MemoryManager = memory_manager

    async def replace(self, file_path: Path, old_text: str, new_text: str,
                     is_regex: bool = False, all_occurrences: bool = True) -> int:
        # Read file content
        content: str = await self._read_file_content(file_path)
        
        # Perform replacements
        if is_regex:
            pattern: re.Pattern = re.compile(old_text)
            if all_occurrences:
                new_content: str
                count: int
                new_content, count = pattern.subn(new_text, content)
            else:
                match: re.Match | None = pattern.search(content)
                if match:
                    new_content = content[:match.start()] + new_text + content[match.end():]
                    count = 1
                else:
                    new_content = content
                    count = 0
        else:
            if all_occurrences:
                new_content = content.replace(old_text, new_text)
                count = content.count(old_text)
            else:
                pos: int = content.find(old_text)
                if pos != -1:
                    new_content = content[:pos] + new_text + content[pos + len(old_text):]
                    count = 1
                else:
                    new_content = content
                    count = 0
        
        # Write back if changed
        if count > 0:
            await self._write_file_content(file_path, new_content)
        
        return count

    async def insert_text(self, file_path: Path, line_number: int, 
                         column: int, text: str) -> None:
        lines: list[str] = await self._read_file_lines(file_path)
        
        # Validate line number
        if line_number < 0 or line_number >= len(lines):
            raise ValueError(f"Invalid line number: {line_number}")
        
        line: str = lines[line_number]
        
        # Validate column
        if column < 0 or column > len(line):
            raise ValueError(f"Invalid column: {column}")
        
        # Insert text
        new_line: str = line[:column] + text + line[column:]
        lines[line_number] = new_line
        
        # Write back
        await self._write_file_lines(file_path, lines)

    async def delete_range(self, file_path: Path, text_range: TextRange) -> str:
        lines: list[str] = await self._read_file_lines(file_path)
        
        # Validate range
        if text_range.start_line < 0 or text_range.end_line >= len(lines):
            raise ValueError("Invalid line range")
        
        # Extract deleted text
        deleted_text: str = ""
        
        if text_range.start_line == text_range.end_line:
            # Single line deletion
            line: str = lines[text_range.start_line]
            deleted_text = line[text_range.start_column:text_range.end_column]
            new_line: str = line[:text_range.start_column] + line[text_range.end_column:]
            lines[text_range.start_line] = new_line
        else:
            # Multi-line deletion
            for i in range(text_range.start_line, text_range.end_line + 1):
                if i == text_range.start_line:
                    deleted_text += lines[i][text_range.start_column:] + '\n'
                    lines[i] = lines[i][:text_range.start_column]
                elif i == text_range.end_line:
                    deleted_text += lines[i][:text_range.end_column]
                    lines[i] = lines[i][text_range.end_column:]
                else:
                    deleted_text += lines[i] + '\n'
                    lines[i] = ""
            
            # Merge first and last lines
            lines[text_range.start_line] += lines[text_range.end_line]
            
            # Remove empty lines in between
            del lines[text_range.start_line + 1:text_range.end_line + 1]
        
        # Write back
        await self._write_file_lines(file_path, lines)
        
        return deleted_text

    async def duplicate_lines(self, file_path: Path, start_line: int, 
                            end_line: int) -> None:
        lines: list[str] = await self._read_file_lines(file_path)
        
        # Validate range
        if start_line < 0 or end_line >= len(lines) or start_line > end_line:
            raise ValueError("Invalid line range")
        
        # Duplicate lines
        duplicated: list[str] = lines[start_line:end_line + 1]
        lines[end_line + 1:end_line + 1] = duplicated
        
        # Write back
        await self._write_file_lines(file_path, lines)

    async def move_lines(self, file_path: Path, start_line: int, 
                        end_line: int, target_line: int) -> None:
        lines: list[str] = await self._read_file_lines(file_path)
        
        # Validate range
        if start_line < 0 or end_line >= len(lines) or start_line > end_line:
            raise ValueError("Invalid line range")
        
        if target_line < 0 or target_line > len(lines):
            raise ValueError("Invalid target line")
        
        # Extract lines to move
        moving_lines: list[str] = lines[start_line:end_line + 1]
        
        # Remove from original position
        del lines[start_line:end_line + 1]
        
        # Adjust target if necessary
        if target_line > start_line:
            target_line -= (end_line - start_line + 1)
        
        # Insert at new position
        lines[target_line:target_line] = moving_lines
        
        # Write back
        await self._write_file_lines(file_path, lines)

    async def transform_text(self, file_path: Path, transformation: str) -> None:
        content: str = await self._read_file_content(file_path)
        
        if transformation == "uppercase":
            new_content: str = content.upper()
        elif transformation == "lowercase":
            new_content: str = content.lower()
        elif transformation == "title":
            new_content: str = content.title()
        elif transformation == "capitalize":
            new_content: str = content.capitalize()
        else:
            raise ValueError(f"Unknown transformation: {transformation}")
        
        await self._write_file_content(file_path, new_content)

    async def trim_whitespace(self, file_path: Path, mode: str = "trailing") -> None:
        lines: list[str] = await self._read_file_lines(file_path)
        
        if mode == "trailing":
            lines = [line.rstrip() for line in lines]
        elif mode == "leading":
            lines = [line.lstrip() for line in lines]
        elif mode == "both":
            lines = [line.strip() for line in lines]
        else:
            raise ValueError(f"Unknown trim mode: {mode}")
        
        await self._write_file_lines(file_path, lines)

    async def _read_file_content(self, file_path: Path) -> str:
        # Use memory manager for efficient reading
        if file_path.stat().st_size > self.memory_manager.config.memory_mapped_threshold:
            return await self.memory_manager.read_mapped_file(file_path)
        else:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()

    async def _read_file_lines(self, file_path: Path) -> list[str]:
        content: str = await self._read_file_content(file_path)
        return content.splitlines(keepends=True)

    async def _write_file_content(self, file_path: Path, content: str) -> None:
        # Use transaction manager for atomic writes
        transaction_id: str = await self.transaction_manager.begin()
        
        try:
            await self.transaction_manager.acquire_file_lock(transaction_id, file_path)
            await self.transaction_manager.write_to_temp(
                transaction_id, file_path, content.encode('utf-8')
            )
            await self.transaction_manager.commit(transaction_id)
        except Exception as e:
            await self.transaction_manager.rollback(transaction_id)
            raise e

    async def _write_file_lines(self, file_path: Path, lines: list[str]) -> None:
        content: str = ''.join(lines)
        await self._write_file_content(file_path, content)
