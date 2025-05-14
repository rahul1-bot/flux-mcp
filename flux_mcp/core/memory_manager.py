from __future__ import annotations

import mmap
import asyncio
from pathlib import Path
from typing import Any
from dataclasses import dataclass, field
from collections import OrderedDict


@dataclass 
class MemoryConfig:
    memory_mapped_threshold: int
    chunk_size: int
    cache_size: int
    
    
@dataclass
class MappedFile:
    path: Path
    mmap_obj: mmap.mmap
    file_handle: Any
    size: int
    line_index: list[int] = field(default_factory=list)
    

class MemoryManager:
    def __init__(self, config: MemoryConfig) -> None:
        self.config: MemoryConfig = config
        self.mapped_files: dict[Path, MappedFile] = {}
        self.cache: OrderedDict[str, bytes] = OrderedDict()
        self.cache_size: int = 0
        self.lock: asyncio.Lock = asyncio.Lock()

    async def read_mapped_file(self, file_path: Path, encoding: str | None = None,
                             start_line: int | None = None, end_line: int | None = None) -> str:
        async with self.lock:
            if file_path not in self.mapped_files:
                await self._map_file(file_path)
            
            mapped_file: MappedFile = self.mapped_files[file_path]
            
            # Build line index if not exists
            if not mapped_file.line_index:
                await self._build_line_index(mapped_file)
            
            # Get content based on line range
            if start_line is not None or end_line is not None:
                content: bytes = await self._read_lines(mapped_file, start_line, end_line)
            else:
                content: bytes = mapped_file.mmap_obj[:]
            
            # Handle encoding
            if encoding is None:
                encoding = self._detect_encoding(content[:1024])
            
            return content.decode(encoding)

    async def _map_file(self, file_path: Path) -> None:
        loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
        mapped_file: MappedFile = await loop.run_in_executor(
            None, self._map_file_sync, file_path
        )
        self.mapped_files[file_path] = mapped_file

    def _map_file_sync(self, file_path: Path) -> MappedFile:
        file_handle: Any = open(file_path, 'rb')
        file_size: int = file_path.stat().st_size
        
        if file_size == 0:
            mmap_obj: mmap.mmap = mmap.mmap(-1, 0)
        else:
            mmap_obj: mmap.mmap = mmap.mmap(
                file_handle.fileno(), 
                0, 
                access=mmap.ACCESS_READ
            )
        
        return MappedFile(
            path=file_path,
            mmap_obj=mmap_obj,
            file_handle=file_handle,
            size=file_size
        )

    async def _build_line_index(self, mapped_file: MappedFile) -> None:
        loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
        line_index: list[int] = await loop.run_in_executor(
            None, self._build_index_sync, mapped_file.mmap_obj
        )
        mapped_file.line_index = line_index

    def _build_index_sync(self, mmap_obj: mmap.mmap) -> list[int]:
        line_index: list[int] = [0]
        position: int = 0
        
        while True:
            line_end: int = mmap_obj.find(b'\n', position)
            if line_end == -1:
                break
            position = line_end + 1
            line_index.append(position)
        
        return line_index

    async def _read_lines(self, mapped_file: MappedFile, 
                         start_line: int | None, end_line: int | None) -> bytes:
        line_count: int = len(mapped_file.line_index)
        
        if start_line is None:
            start_line = 0
        if end_line is None:
            end_line = line_count - 1
        
        start_line = max(0, min(start_line, line_count - 1))
        end_line = max(0, min(end_line, line_count - 1))
        
        start_pos: int = mapped_file.line_index[start_line]
        
        if end_line >= line_count - 1:
            end_pos: int = mapped_file.size
        else:
            end_pos: int = mapped_file.line_index[end_line + 1]
        
        return mapped_file.mmap_obj[start_pos:end_pos]

    def _detect_encoding(self, sample: bytes) -> str:
        # Simple encoding detection (can be enhanced)
        try:
            sample.decode('utf-8')
            return 'utf-8'
        except UnicodeDecodeError:
            try:
                sample.decode('utf-16')
                return 'utf-16'
            except UnicodeDecodeError:
                return 'latin-1'

    async def read_chunks(self, file_path: Path, chunk_size: int | None = None) -> AsyncIterator[bytes]:
        if chunk_size is None:
            chunk_size = self.config.chunk_size
        
        loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
        
        with open(file_path, 'rb') as f:
            while True:
                chunk: bytes = await loop.run_in_executor(None, f.read, chunk_size)
                if not chunk:
                    break
                yield chunk

    async def cache_put(self, key: str, value: bytes) -> None:
        async with self.lock:
            # Remove if already exists
            if key in self.cache:
                old_value: bytes = self.cache.pop(key)
                self.cache_size -= len(old_value)
            
            # Check cache size limit
            while self.cache_size + len(value) > self.config.cache_size and self.cache:
                oldest_key: str
                oldest_value: bytes
                oldest_key, oldest_value = self.cache.popitem(last=False)
                self.cache_size -= len(oldest_value)
            
            # Add new item
            self.cache[key] = value
            self.cache_size += len(value)

    async def cache_get(self, key: str) -> bytes | None:
        async with self.lock:
            if key in self.cache:
                # Move to end (LRU)
                value: bytes = self.cache.pop(key)
                self.cache[key] = value
                return value
            return None

    def close_mapped_file(self, file_path: Path) -> None:
        if file_path in self.mapped_files:
            mapped_file: MappedFile = self.mapped_files.pop(file_path)
            mapped_file.mmap_obj.close()
            mapped_file.file_handle.close()

    def __del__(self) -> None:
        for mapped_file in self.mapped_files.values():
            try:
                mapped_file.mmap_obj.close()
                mapped_file.file_handle.close()
            except Exception:
                pass


from typing import AsyncIterator
