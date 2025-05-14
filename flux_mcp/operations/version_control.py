from __future__ import annotations

import sqlite3
import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import Any
from dataclasses import dataclass, asdict


@dataclass
class Checkpoint:
    id: str
    name: str
    timestamp: datetime
    file_path: Path
    content_hash: str
    content: bytes
    metadata: dict[str, Any]
    parent_id: str | None = None


@dataclass
class UndoEntry:
    id: str
    timestamp: datetime
    operation_type: str
    file_path: Path
    old_content: bytes
    new_content: bytes
    metadata: dict[str, Any]


class VersionControl:
    def __init__(self, db_path: Path | None = None) -> None:
        if db_path is None:
            db_path = Path.home() / '.flux' / 'version_control.db'
        
        self.db_path: Path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._init_database()

    def _init_database(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS checkpoints (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    file_path TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    content BLOB NOT NULL,
                    metadata TEXT NOT NULL,
                    parent_id TEXT
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS undo_entries (
                    id TEXT PRIMARY KEY,
                    timestamp REAL NOT NULL,
                    operation_type TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    old_content BLOB NOT NULL,
                    new_content BLOB NOT NULL,
                    metadata TEXT NOT NULL
                )
            ''')
            
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_checkpoints_file 
                ON checkpoints(file_path)
            ''')
            
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_undo_file 
                ON undo_entries(file_path)
            ''')

    async def create_checkpoint(self, name: str, file_path: Path, 
                              content: bytes, metadata: dict[str, Any] | None = None) -> str:
        import uuid
        import hashlib
        
        checkpoint_id: str = str(uuid.uuid4())
        content_hash: str = hashlib.sha256(content).hexdigest()
        
        checkpoint: Checkpoint = Checkpoint(
            id=checkpoint_id,
            name=name,
            timestamp=datetime.now(),
            file_path=file_path,
            content_hash=content_hash,
            content=content,
            metadata=metadata or {}
        )
        
        loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._save_checkpoint, checkpoint)
        
        return checkpoint_id

    def _save_checkpoint(self, checkpoint: Checkpoint) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT INTO checkpoints 
                (id, name, timestamp, file_path, content_hash, content, metadata, parent_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                checkpoint.id,
                checkpoint.name,
                checkpoint.timestamp.timestamp(),
                str(checkpoint.file_path),
                checkpoint.content_hash,
                checkpoint.content,
                json.dumps(checkpoint.metadata),
                checkpoint.parent_id
            ))

    async def restore_checkpoint(self, checkpoint_id: str) -> Checkpoint:
        loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._load_checkpoint, checkpoint_id)

    def _load_checkpoint(self, checkpoint_id: str) -> Checkpoint:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('''
                SELECT id, name, timestamp, file_path, content_hash, 
                       content, metadata, parent_id
                FROM checkpoints 
                WHERE id = ?
            ''', (checkpoint_id,))
            
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Checkpoint not found: {checkpoint_id}")
            
            return Checkpoint(
                id=row[0],
                name=row[1],
                timestamp=datetime.fromtimestamp(row[2]),
                file_path=Path(row[3]),
                content_hash=row[4],
                content=row[5],
                metadata=json.loads(row[6]),
                parent_id=row[7]
            )

    async def add_undo_entry(self, operation_type: str, file_path: Path,
                           old_content: bytes, new_content: bytes,
                           metadata: dict[str, Any] | None = None) -> str:
        import uuid
        
        entry_id: str = str(uuid.uuid4())
        
        entry: UndoEntry = UndoEntry(
            id=entry_id,
            timestamp=datetime.now(),
            operation_type=operation_type,
            file_path=file_path,
            old_content=old_content,
            new_content=new_content,
            metadata=metadata or {}
        )
        
        loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._save_undo_entry, entry)
        
        return entry_id

    def _save_undo_entry(self, entry: UndoEntry) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT INTO undo_entries 
                (id, timestamp, operation_type, file_path, old_content, new_content, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                entry.id,
                entry.timestamp.timestamp(),
                entry.operation_type,
                str(entry.file_path),
                entry.old_content,
                entry.new_content,
                json.dumps(entry.metadata)
            ))

    async def undo(self, entry_id: str) -> UndoEntry:
        loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
        entry: UndoEntry = await loop.run_in_executor(None, self._load_undo_entry, entry_id)
        
        # Create reverse undo entry for redo capability
        await self.add_undo_entry(
            f"redo_{entry.operation_type}",
            entry.file_path,
            entry.new_content,
            entry.old_content,
            {'original_entry_id': entry.id}
        )
        
        return entry

    def _load_undo_entry(self, entry_id: str) -> UndoEntry:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('''
                SELECT id, timestamp, operation_type, file_path, 
                       old_content, new_content, metadata
                FROM undo_entries 
                WHERE id = ?
            ''', (entry_id,))
            
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Undo entry not found: {entry_id}")
            
            return UndoEntry(
                id=row[0],
                timestamp=datetime.fromtimestamp(row[1]),
                operation_type=row[2],
                file_path=Path(row[3]),
                old_content=row[4],
                new_content=row[5],
                metadata=json.loads(row[6])
            )

    async def list_checkpoints(self, file_path: Path | None = None) -> list[dict[str, Any]]:
        loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._list_checkpoints, file_path)

    def _list_checkpoints(self, file_path: Path | None = None) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            if file_path:
                cursor = conn.execute('''
                    SELECT id, name, timestamp, file_path, content_hash
                    FROM checkpoints 
                    WHERE file_path = ?
                    ORDER BY timestamp DESC
                ''', (str(file_path),))
            else:
                cursor = conn.execute('''
                    SELECT id, name, timestamp, file_path, content_hash
                    FROM checkpoints 
                    ORDER BY timestamp DESC
                ''')
            
            return [
                {
                    'id': row[0],
                    'name': row[1],
                    'timestamp': datetime.fromtimestamp(row[2]).isoformat(),
                    'file_path': row[3],
                    'content_hash': row[4]
                }
                for row in cursor
            ]

    async def list_undo_history(self, file_path: Path | None = None, 
                              limit: int = 50) -> list[dict[str, Any]]:
        loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._list_undo_history, file_path, limit)

    def _list_undo_history(self, file_path: Path | None = None, 
                          limit: int = 50) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            if file_path:
                cursor = conn.execute('''
                    SELECT id, timestamp, operation_type, file_path
                    FROM undo_entries 
                    WHERE file_path = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                ''', (str(file_path), limit))
            else:
                cursor = conn.execute('''
                    SELECT id, timestamp, operation_type, file_path
                    FROM undo_entries 
                    ORDER BY timestamp DESC
                    LIMIT ?
                ''', (limit,))
            
            return [
                {
                    'id': row[0],
                    'timestamp': datetime.fromtimestamp(row[1]).isoformat(),
                    'operation_type': row[2],
                    'file_path': row[3]
                }
                for row in cursor
            ]

    async def cleanup_old_entries(self, days: int = 30) -> int:
        cutoff_time: float = (datetime.now() - timedelta(days=days)).timestamp()
        
        loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._cleanup_old_entries, cutoff_time)

    def _cleanup_old_entries(self, cutoff_time: float) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('''
                DELETE FROM checkpoints WHERE timestamp < ?
            ''', (cutoff_time,))
            checkpoints_deleted: int = cursor.rowcount
            
            cursor = conn.execute('''
                DELETE FROM undo_entries WHERE timestamp < ?
            ''', (cutoff_time,))
            undo_deleted: int = cursor.rowcount
            
            return checkpoints_deleted + undo_deleted


from datetime import timedelta
