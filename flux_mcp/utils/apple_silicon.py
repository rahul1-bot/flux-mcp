from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Any


@dataclass
class SiliconInfo:
    chip_type: str
    cpu_cores: int
    gpu_cores: int
    neural_cores: int
    memory_gb: int
    os_version: str
    

class AppleSiliconOptimizer:
    def __init__(self) -> None:
        self.silicon_info: SiliconInfo = self._detect_silicon()

    def _detect_silicon(self) -> SiliconInfo:
        # Platform detection
        system: str = platform.system()
        if system != 'Darwin':
            raise RuntimeError("Not running on macOS")
        
        # Get chip info from platform
        processor: str = platform.processor()
        machine: str = platform.machine()
        
        # Default M3 Max configuration
        if 'arm64' in machine or 'Apple M' in processor:
            return SiliconInfo(
                chip_type='M3 Max',
                cpu_cores=16,
                gpu_cores=40,
                neural_cores=16,
                memory_gb=128,
                os_version=platform.mac_ver()[0]
            )
        else:
            raise RuntimeError("Not running on Apple Silicon")

    def get_optimal_thread_count(self, cpu_intensive: bool = True) -> int:
        if cpu_intensive:
            # Use performance cores for CPU-intensive tasks
            return 12  # M3 Max has 12 performance cores
        else:
            # Use all cores for I/O-bound tasks
            return self.silicon_info.cpu_cores

    def get_optimal_chunk_size(self, file_size: int) -> int:
        # Optimize chunk size based on memory bandwidth
        # M3 Max has 400GB/s memory bandwidth
        
        if file_size < 1024 * 1024:  # < 1MB
            return 64 * 1024  # 64KB chunks
        elif file_size < 10 * 1024 * 1024:  # < 10MB
            return 256 * 1024  # 256KB chunks
        elif file_size < 100 * 1024 * 1024:  # < 100MB
            return 1024 * 1024  # 1MB chunks
        else:
            return 4 * 1024 * 1024  # 4MB chunks

    def should_use_gpu(self, operation_type: str, data_size: int) -> bool:
        # Heuristics for GPU usage
        gpu_operations: set[str] = {
            'regex_search',
            'pattern_matching',
            'parallel_search',
            'bulk_replacement'
        }
        
        if operation_type not in gpu_operations:
            return False
        
        # Use GPU for large data sizes
        return data_size > 1024 * 1024  # > 1MB

    def get_memory_limit(self) -> int:
        # Conservative memory limit (50% of system RAM)
        return (self.silicon_info.memory_gb * 1024 * 1024 * 1024) // 2

    def configure_for_performance(self) -> dict[str, Any]:
        return {
            'thread_pool_size': self.get_optimal_thread_count(cpu_intensive=True),
            'io_thread_pool_size': self.get_optimal_thread_count(cpu_intensive=False),
            'memory_limit': self.get_memory_limit(),
            'chunk_size': 1024 * 1024,  # Default 1MB
            'gpu_enabled': True,
            'cache_size': 1024 * 1024 * 1024,  # 1GB cache
            'prefetch_enabled': True,
            'compression_enabled': True
        }

    def get_system_info(self) -> dict[str, Any]:
        return {
            'chip_type': self.silicon_info.chip_type,
            'cpu_cores': self.silicon_info.cpu_cores,
            'gpu_cores': self.silicon_info.gpu_cores,
            'neural_cores': self.silicon_info.neural_cores,
            'memory_gb': self.silicon_info.memory_gb,
            'os_version': self.silicon_info.os_version,
            'platform': platform.platform(),
            'python_version': platform.python_version()
        }

    def optimize_for_operation(self, operation: str, data_size: int) -> dict[str, Any]:
        config: dict[str, Any] = {
            'use_gpu': self.should_use_gpu(operation, data_size),
            'thread_count': self.get_optimal_thread_count(
                cpu_intensive=operation in ['search', 'replace', 'parse']
            ),
            'chunk_size': self.get_optimal_chunk_size(data_size)
        }
        
        # Operation-specific optimizations
        if operation == 'search':
            config['prefetch_size'] = min(data_size // 10, 10 * 1024 * 1024)
            config['use_simd'] = True
        elif operation == 'replace':
            config['batch_size'] = 1000
            config['use_transactions'] = True
        elif operation == 'parse':
            config['use_ast_cache'] = True
            config['parallel_parse'] = data_size > 1024 * 1024
        
        return config
