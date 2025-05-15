from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
import chardet
import aiofiles
from dataclasses import dataclass

from flux_mcp.core.transaction_manager import TransactionManager
from flux_mcp.core.memory_manager import MemoryManager
from flux_mcp.models.file_state import FileState, FileMetadata
from flux_mcp.utils.file_lock import FileLock


class FileHandler:
    def __init__(self, transaction_manager: TransactionManager, 
                 memory_manager: MemoryManager) -> None:
        self.transaction_manager: TransactionManager = transaction_manager
        self.memory_manager: MemoryManager = memory_manager
        self.file_locks: dict[Path, FileLock] = {}

    async def read_file(self, file_path: Path, encoding: str | None = None,
                       start_line: int | None = None, end_line: int | None = None) -> str:
        # Check cache first
        cache_key: str = f"{file_path}:{start_line}:{end_line}"
        cached_content: bytes | None = await self.memory_manager.cache_get(cache_key)
        
        if cached_content:
            return cached_content.decode(encoding or 'utf-8')
        
        # Read file
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        content: bytes
        
        if start_line is not None or end_line is not None:
            content = await self._read_lines(file_path, start_line, end_line)
        else:
            async with aiofiles.open(file_path, 'rb') as f:
                content = await f.read()
        
        # Detect encoding if not specified
        if encoding is None:
            detected: dict[str, Any] = chardet.detect(content[:1024])
            encoding = detected['encoding'] or 'utf-8'
        
        # Cache the content
        await self.memory_manager.cache_put(cache_key, content)
        
        return content.decode(encoding)

    async def _read_lines(self, file_path: Path, start_line: int | None, 
                         end_line: int | None) -> bytes:
        lines: list[bytes] = []
        current_line: int = 0
        
        async with aiofiles.open(file_path, 'rb') as f:
            async for line in f:
                if start_line is not None and current_line < start_line:
                    current_line += 1
                    continue
                
                if end_line is not None and current_line > end_line:
                    break
                
                if start_line is None or current_line >= start_line:
                    lines.append(line)
                
                current_line += 1
        
        return b''.join(lines)

    async def write_file(self, file_path: Path, content: str, 
                        encoding: str = 'utf-8') -> None:
        # Check if we're already in a transaction
        transaction_id: str | None = None
        commit_needed: bool = False
        
        # Check if there's an active transaction
        if hasattr(self, '_current_transaction_id'):
            transaction_id = self._current_transaction_id
        else:
            # Create a new transaction if none exists
            transaction_id = await self.transaction_manager.begin()
            commit_needed = True
        
        try:
            # Acquire file lock through transaction manager
            await self.transaction_manager.acquire_file_lock(transaction_id, file_path)
            
            # Write to temp file
            content_bytes: bytes = content.encode(encoding)
            await self.transaction_manager.write_to_temp(
                transaction_id, file_path, content_bytes
            )
            
            # Clear cache for this file
            await self._clear_file_cache(file_path)
            
            # Commit if we created the transaction
            if commit_needed:
                await self.transaction_manager.commit(transaction_id)
            
        except Exception as e:
            if commit_needed:
                await self.transaction_manager.rollback(transaction_id)
            raise e

    async def _clear_file_cache(self, file_path: Path) -> None:
        # Clear all cache entries for this file
        cache_keys: list[str] = []
        async with self.memory_manager.lock:
            for key in self.memory_manager.cache.keys():
                if key.startswith(str(file_path)):
                    cache_keys.append(key)
        
        for key in cache_keys:
            self.memory_manager.cache.pop(key, None)

    async def get_file_metadata(self, file_path: Path) -> FileMetadata:
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        stat = file_path.stat()
        
        # Detect if binary
        is_binary: bool = await self._is_binary_file(file_path)
        
        # Detect encoding for text files
        detected_encoding: str | None = None
        if not is_binary:
            sample: bytes
            async with aiofiles.open(file_path, 'rb') as f:
                sample = await f.read(1024)
            detected: dict[str, Any] = chardet.detect(sample)
            detected_encoding = detected['encoding']
        
        # Detect line endings
        line_endings: str = await self._detect_line_endings(file_path)
        
        return FileMetadata(
            path=file_path,
            size=stat.st_size,
            created_time=datetime.fromtimestamp(stat.st_ctime),
            modified_time=datetime.fromtimestamp(stat.st_mtime),
            permissions=stat.st_mode,
            owner=str(stat.st_uid),
            group=str(stat.st_gid),
            is_binary=is_binary,
            detected_encoding=detected_encoding,
            line_endings=line_endings
        )

    async def _is_binary_file(self, file_path: Path) -> bool:
        try:
            sample: bytes
            async with aiofiles.open(file_path, 'rb') as f:
                sample = await f.read(1024)
            
            # Check for null bytes
            return b'\x00' in sample
        except Exception:
            return True

    async def _detect_line_endings(self, file_path: Path) -> str:
        try:
            sample: bytes
            async with aiofiles.open(file_path, 'rb') as f:
                sample = await f.read(8192)
            
            if b'\r\n' in sample:
                return 'CRLF'
            elif b'\r' in sample:
                return 'CR'
            elif b'\n' in sample:
                return 'LF'
            else:
                return 'None'
        except Exception:
            return 'Unknown'

    async def copy_file(self, source: Path, destination: Path) -> None:
        if not source.exists():
            raise FileNotFoundError(f"Source file not found: {source}")
        
        # Create destination directory if needed
        destination.parent.mkdir(parents=True, exist_ok=True)
        
        # Copy file
        async with aiofiles.open(source, 'rb') as src:
            async with aiofiles.open(destination, 'wb') as dst:
                while True:
                    chunk: bytes = await src.read(self.memory_manager.config.chunk_size)
                    if not chunk:
                        break
                    await dst.write(chunk)
        
        # Copy metadata
        source_stat = source.stat()
        destination.chmod(source_stat.st_mode)

    async def move_file(self, source: Path, destination: Path) -> None:
        await self.copy_file(source, destination)
        source.unlink()

    async def delete_file(self, file_path: Path) -> None:
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Clear cache
        await self._clear_file_cache(file_path)
        
        # Delete file
        file_path.unlink()


from datetime import datetime
