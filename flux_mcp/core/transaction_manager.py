from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any
from dataclasses import dataclass, field
from datetime import datetime
import fcntl
import tempfile
import shutil


@dataclass
class Transaction:
    id: str
    timestamp: datetime
    file_locks: dict[Path, int] = field(default_factory=dict)
    file_handles: dict[Path, Any] = field(default_factory=dict)
    original_states: dict[Path, bytes] = field(default_factory=dict)
    temp_files: dict[Path, Path] = field(default_factory=dict)
    is_committed: bool = False
    is_rolled_back: bool = False


class TransactionManager:
    def __init__(self) -> None:
        self.transactions: dict[str, Transaction] = {}
        self.lock: asyncio.Lock = asyncio.Lock()

    async def begin(self) -> str:
        async with self.lock:
            transaction_id: str = str(uuid.uuid4())
            transaction: Transaction = Transaction(
                id=transaction_id,
                timestamp=datetime.now()
            )
            self.transactions[transaction_id] = transaction
            return transaction_id

    async def acquire_file_lock(self, transaction_id: str, file_path: Path) -> None:
        async with self.lock:
            transaction: Transaction = self.transactions.get(transaction_id)
            if not transaction:
                raise ValueError(f"Invalid transaction ID: {transaction_id}")
            
            if transaction.is_committed or transaction.is_rolled_back:
                raise ValueError("Transaction already finished")
            
            # Open file and acquire exclusive lock
            loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
            fd: int
            file_handle: Any
            fd, file_handle = await loop.run_in_executor(
                None, self._acquire_lock_sync, file_path
            )
            
            transaction.file_locks[file_path] = fd
            transaction.file_handles[file_path] = file_handle
            
            # Read current state for rollback capability if file exists
            if file_path.exists():
                with open(file_path, 'rb') as f:
                    transaction.original_states[file_path] = f.read()
            else:
                transaction.original_states[file_path] = b''
            
            # Create temp file for atomic operations
            temp_fd: int
            temp_path: str
            temp_fd, temp_path = tempfile.mkstemp(
                dir=file_path.parent,
                prefix=f".{file_path.name}.",
                suffix=".tmp"
            )
            transaction.temp_files[file_path] = Path(temp_path)

    def _acquire_lock_sync(self, file_path: Path) -> tuple[int, Any]:
        # Create parent directories if they don't exist
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create file if it doesn't exist
        if not file_path.exists():
            file_path.touch()
        
        # Open file for reading and writing
        file_handle = open(file_path, 'r+b')
        fd: int = file_handle.fileno()
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd, file_handle

    async def write_to_temp(self, transaction_id: str, file_path: Path, content: bytes) -> None:
        async with self.lock:
            transaction: Transaction = self.transactions.get(transaction_id)
            if not transaction:
                raise ValueError(f"Invalid transaction ID: {transaction_id}")
            
            temp_path: Path = transaction.temp_files.get(file_path)
            if not temp_path:
                raise ValueError(f"No lock acquired for file: {file_path}")
            
            loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, self._write_temp_sync, temp_path, content
            )

    def _write_temp_sync(self, temp_path: Path, content: bytes) -> None:
        with open(temp_path, 'wb') as f:
            f.write(content)
            f.flush()
            import os
            os.fsync(f.fileno())

    async def commit(self, transaction_id: str) -> None:
        async with self.lock:
            transaction: Transaction = self.transactions.get(transaction_id)
            if not transaction:
                raise ValueError(f"Invalid transaction ID: {transaction_id}")
            
            if transaction.is_committed or transaction.is_rolled_back:
                raise ValueError("Transaction already finished")
            
            try:
                # Atomic rename of all temp files
                for original_path, temp_path in transaction.temp_files.items():
                    shutil.move(str(temp_path), str(original_path))
                
                transaction.is_committed = True
            finally:
                self._release_all_locks(transaction)

    async def rollback(self, transaction_id: str) -> None:
        async with self.lock:
            transaction: Transaction = self.transactions.get(transaction_id)
            if not transaction:
                raise ValueError(f"Invalid transaction ID: {transaction_id}")
            
            if transaction.is_committed or transaction.is_rolled_back:
                raise ValueError("Transaction already finished")
            
            try:
                # Restore original states
                for file_path, original_state in transaction.original_states.items():
                    if original_state:  # Only restore if there was original content
                        with open(file_path, 'wb') as f:
                            f.write(original_state)
                    elif file_path.exists():
                        # If file was new and transaction is rolling back, remove it
                        file_path.unlink()
                
                # Clean up temp files
                for temp_path in transaction.temp_files.values():
                    if temp_path.exists():
                        temp_path.unlink()
                
                transaction.is_rolled_back = True
            finally:
                self._release_all_locks(transaction)

    def _release_all_locks(self, transaction: Transaction) -> None:
        for file_path, fd in transaction.file_locks.items():
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except Exception:
                pass
        
        # Close file handles
        for file_handle in transaction.file_handles.values():
            try:
                file_handle.close()
            except Exception:
                pass
