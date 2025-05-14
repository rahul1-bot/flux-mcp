from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from datetime import datetime
from pathlib import Path


@dataclass
class Operation:
    id: str
    type: str
    timestamp: datetime
    parameters: dict[str, Any]
    status: str
    result: Any | None = None
    error: str | None = None
    duration_ms: float | None = None


@dataclass
class ReadOperation(Operation):
    file_path: Path
    encoding: str | None
    start_line: int | None
    end_line: int | None
    bytes_read: int | None = None


@dataclass
class WriteOperation(Operation):
    file_path: Path
    content: str
    encoding: str
    create_dirs: bool
    bytes_written: int | None = None


@dataclass
class SearchOperation(Operation):
    file_path: Path
    pattern: str
    is_regex: bool
    case_sensitive: bool
    whole_word: bool
    matches_found: int | None = None


@dataclass
class ReplaceOperation(Operation):
    file_path: Path
    old_text: str
    new_text: str
    is_regex: bool
    all_occurrences: bool
    replacements_made: int | None = None
