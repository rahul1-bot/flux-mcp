from __future__ import annotations

import fcntl
import asyncio
from pathlib import Path
from typing import Any
from dataclasses import dataclass


@dataclass
class LockInfo:
    file_path: Path
    fd: int
    is_exclusive: bool
    

class FileLock:
    def __init__(self, file_path: Path, exclusive: bool = True) -> None:
        self.file_path: Path = file_path
        self.exclusive: bool = exclusive
        self.fd: int | None = None
        self.is_locked: bool = False

    async def acquire(self, timeout: float | None = None) -> bool:
        if self.is_locked:
            return True
        
        loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
        
        try:
            self.fd = await loop.run_in_executor(
                None, self._acquire_lock_sync, timeout
            )
            self.is_locked = True
            return True
        except Exception:
            return False

    def _acquire_lock_sync(self, timeout: float | None) -> int:
        fd: int = open(self.file_path, 'r+b').fileno()
        
        lock_type: int = fcntl.LOCK_EX if self.exclusive else fcntl.LOCK_SH
        flags: int = lock_type | fcntl.LOCK_NB
        
        if timeout is None:
            fcntl.flock(fd, lock_type)
        else:
            import time
            start_time: float = time.time()
            
            while True:
                try:
                    fcntl.flock(fd, flags)
                    break
                except IOError:
                    if time.time() - start_time > timeout:
                        raise TimeoutError("Failed to acquire lock")
                    time.sleep(0.1)
        
        return fd

    async def release(self) -> None:
        if not self.is_locked or self.fd is None:
            return
        
        loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._release_lock_sync)
        
        self.is_locked = False
        self.fd = None

    def _release_lock_sync(self) -> None:
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            fcntl.close(self.fd)

    async def __aenter__(self) -> 'FileLock':
        await self.acquire()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.release()


class FileLockManager:
    def __init__(self) -> None:
        self.locks: dict[Path, FileLock] = {}
        self.lock: asyncio.Lock = asyncio.Lock()

    async def acquire_lock(self, file_path: Path, exclusive: bool = True, 
                          timeout: float | None = None) -> FileLock:
        async with self.lock:
            if file_path in self.locks:
                existing_lock: FileLock = self.locks[file_path]
                if existing_lock.is_locked:
                    if not exclusive and not existing_lock.exclusive:
                        # Shared locks can coexist
                        return existing_lock
                    else:
                        raise ValueError(f"File already locked: {file_path}")
            
            file_lock: FileLock = FileLock(file_path, exclusive)
            success: bool = await file_lock.acquire(timeout)
            
            if not success:
                raise TimeoutError(f"Failed to acquire lock for: {file_path}")
            
            self.locks[file_path] = file_lock
            return file_lock

    async def release_lock(self, file_path: Path) -> None:
        async with self.lock:
            if file_path in self.locks:
                file_lock: FileLock = self.locks.pop(file_path)
                await file_lock.release()

    async def is_locked(self, file_path: Path) -> bool:
        async with self.lock:
            if file_path in self.locks:
                return self.locks[file_path].is_locked
            return False

    async def cleanup(self) -> None:
        async with self.lock:
            for file_lock in self.locks.values():
                await file_lock.release()
            self.locks.clear()
