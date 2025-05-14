from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
from typing import Any


@dataclass
class FileState:
    path: Path
    size: int
    modified_time: datetime
    content_hash: str
    encoding: str
    line_count: int
    is_locked: bool = False
    lock_holder: str | None = None
    

@dataclass
class FileSnapshot:
    file_state: FileState
    content: bytes
    timestamp: datetime
    transaction_id: str | None = None
    

@dataclass 
class FileMetadata:
    path: Path
    size: int
    created_time: datetime
    modified_time: datetime
    permissions: int
    owner: str
    group: str
    is_binary: bool
    detected_encoding: str | None
    line_endings: str
