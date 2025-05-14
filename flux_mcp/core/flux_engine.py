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
        
        if file_path.stat().st_size > self.config.memory_mapped_threshold:
            return await self.memory_manager.read_mapped_file(
                file_path, encoding, start_line, end_line
            )
        else:
            return await self.file_handler.read_file(
                file_path, encoding, start_line, end_line
            )

    async def write_file(self, path: str, content: str, 
                        encoding: str = "utf-8", create_dirs: bool = True) -> str:
        file_path: Path = Path(path)
        
        if create_dirs and not file_path.parent.exists():
            file_path.parent.mkdir(parents=True, exist_ok=True)
        
        transaction_id: str = await self.transaction_manager.begin()
        
        try:
            await self.file_handler.write_file(file_path, content, encoding)
            await self.transaction_manager.commit(transaction_id)
            return f"Successfully wrote to {path}"
        except Exception as e:
            await self.transaction_manager.rollback(transaction_id)
            raise Exception(f"Failed to write file: {e}")

    async def search(self, path: str, pattern: str, is_regex: bool = False, 
                    case_sensitive: bool = True, whole_word: bool = False) -> list[dict[str, Any]]:
        file_path: Path = Path(path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        return await self.search_engine.search(
            file_path, pattern, is_regex, case_sensitive, whole_word
        )

    async def replace(self, path: str, old_text: str, new_text: str, 
                     is_regex: bool = False, all_occurrences: bool = True) -> str:
        file_path: Path = Path(path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        transaction_id: str = await self.transaction_manager.begin()
        
        try:
            count: int = await self.text_editor.replace(
                file_path, old_text, new_text, is_regex, all_occurrences
            )
            await self.transaction_manager.commit(transaction_id)
            return f"Replaced {count} occurrences in {path}"
        except Exception as e:
            await self.transaction_manager.rollback(transaction_id)
            raise Exception(f"Failed to replace text: {e}")

    def __del__(self) -> None:
        self.executor.shutdown(wait=True)
