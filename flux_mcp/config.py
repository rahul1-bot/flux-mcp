from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class FluxConfig:
    # Memory management
    memory_mapped_threshold: int = 10 * 1024 * 1024  # 10MB
    chunk_size: int = 1024 * 1024  # 1MB
    cache_size: int = 1024 * 1024 * 1024  # 1GB
    
    # Threading
    worker_count: int = 15
    io_thread_count: int = 4
    
    # GPU acceleration
    gpu_enabled: bool = True
    gpu_threshold: int = 10 * 1024  # 10KB
    
    # File operations
    max_file_size: int = 10 * 1024 * 1024 * 1024  # 10GB
    temp_dir: Path = field(default_factory=lambda: Path.home() / '.flux' / 'temp')
    
    # Search settings
    max_search_results: int = 10000
    search_timeout_seconds: float = 30.0
    
    # Version control
    checkpoint_dir: Path = field(default_factory=lambda: Path.home() / '.flux' / 'checkpoints')
    max_checkpoints_per_file: int = 100
    checkpoint_compression: bool = True
    
    # Transaction settings
    transaction_timeout_seconds: float = 300.0
    max_concurrent_transactions: int = 50
    
    # Logging
    log_level: str = 'INFO'
    log_file: Path = field(default_factory=lambda: Path.home() / '.flux' / 'flux.log')
    
    # Performance
    prefetch_size: int = 5 * 1024 * 1024  # 5MB
    use_mmap_always: bool = False
    
    def __post_init__(self) -> None:
        # Create directories if they don't exist
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_dict(cls, config_dict: dict[str, Any]) -> 'FluxConfig':
        # Convert string paths to Path objects
        if 'temp_dir' in config_dict:
            config_dict['temp_dir'] = Path(config_dict['temp_dir'])
        if 'checkpoint_dir' in config_dict:
            config_dict['checkpoint_dir'] = Path(config_dict['checkpoint_dir'])
        if 'log_file' in config_dict:
            config_dict['log_file'] = Path(config_dict['log_file'])
        
        return cls(**config_dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        
        for field_name, field_value in self.__dict__.items():
            if isinstance(field_value, Path):
                result[field_name] = str(field_value)
            else:
                result[field_name] = field_value
        
        return result


@dataclass
class RuntimeConfig:
    debug_mode: bool = False
    profile_enabled: bool = False
    metrics_enabled: bool = True
    
    # Runtime limits
    max_memory_usage: int = 8 * 1024 * 1024 * 1024  # 8GB
    max_cpu_percent: float = 80.0
    
    # Timeouts
    operation_timeout: float = 60.0
    network_timeout: float = 30.0
    
    # Feature flags
    enable_experimental_features: bool = False
    enable_background_indexing: bool = True
    enable_auto_recovery: bool = True
