from __future__ import annotations

import re
import sys
import platform
from typing import Any
from dataclasses import dataclass
import numpy as np
import multiprocessing

# Check if we're on macOS before importing Metal
if platform.system() == "Darwin":
    try:
        import Metal
        import CoreGraphics
        import objc
        METAL_AVAILABLE = True
    except ImportError:
        METAL_AVAILABLE = False
else:
    METAL_AVAILABLE = False


@dataclass
class CompiledPattern:
    pattern: str
    regex: re.Pattern | None
    metal_function: Any | None = None
    is_simple: bool = False


class MetalAccelerator:
    def __init__(self) -> None:
        self.device: Any = None
        self.command_queue: Any = None
        self.library: Any = None
        self.pattern_cache: dict[str, CompiledPattern] = {}
        self._initialized: bool = False
        self._metal_available: bool = METAL_AVAILABLE
        
        # Don't initialize Metal in parent process if using multiprocessing
        if multiprocessing.current_process().name == 'MainProcess':
            self._metal_available = False

    def _initialize_metal(self) -> bool:
        """Initialize Metal resources if available and not already initialized"""
        if not self._metal_available or self._initialized:
            return self._initialized
        
        try:
            # Only initialize in child processes or when explicitly needed
            if multiprocessing.current_process().name != 'MainProcess':
                self.device = Metal.MTLCreateSystemDefaultDevice()
                if self.device is None:
                    return False
                
                self.command_queue = self.device.newCommandQueue()
                self._compile_shaders()
                self._initialized = True
                return True
        except Exception:
            self._metal_available = False
        
        return False

    def _compile_shaders(self) -> None:
        """Compile Metal shader library"""
        if not self.device:
            return
        
        shader_source: str = """
        #include <metal_stdlib>
        using namespace metal;
        
        kernel void simple_search(device const char* text [[buffer(0)]],
                                  device const char* pattern [[buffer(1)]],
                                  constant uint& text_length [[buffer(2)]],
                                  constant uint& pattern_length [[buffer(3)]],
                                  device uint* matches [[buffer(4)]],
                                  device atomic_uint* match_count [[buffer(5)]],
                                  uint gid [[thread_position_in_grid]]) {
            
            if (gid >= text_length - pattern_length + 1) {
                return;
            }
            
            bool found = true;
            for (uint i = 0; i < pattern_length; i++) {
                if (text[gid + i] != pattern[i]) {
                    found = false;
                    break;
                }
            }
            
            if (found) {
                uint idx = atomic_fetch_add_explicit(match_count, 1, memory_order_relaxed);
                matches[idx] = gid;
            }
        }
        """
        
        try:
            compile_options: Any = Metal.MTLCompileOptions.new()
            self.library = self.device.newLibraryWithSource_options_error_(
                shader_source, compile_options, None
            )
        except Exception:
            self.library = None

    def compile_pattern(self, pattern: str, is_regex: bool = False) -> CompiledPattern:
        if pattern in self.pattern_cache:
            return self.pattern_cache[pattern]
        
        compiled: CompiledPattern = CompiledPattern(
            pattern=pattern,
            regex=re.compile(pattern) if is_regex else None,
            is_simple=not is_regex and self._is_simple_pattern(pattern)
        )
        
        # Only try GPU compilation for simple patterns
        if compiled.is_simple and self._initialize_metal():
            try:
                compiled.metal_function = self.library.newFunctionWithName_("simple_search")
            except Exception:
                compiled.metal_function = None
        
        self.pattern_cache[pattern] = compiled
        return compiled

    def _is_simple_pattern(self, pattern: str) -> bool:
        # Check if pattern is simple enough for GPU acceleration
        return bool(re.match(r'^[a-zA-Z0-9\s]+$', pattern))

    def search_gpu(self, text: bytes, pattern: CompiledPattern) -> list[int]:
        # Try GPU acceleration if available
        if pattern.metal_function and self._initialized:
            try:
                return self._search_gpu_metal(text, pattern)
            except Exception:
                # Fall back to CPU on any error
                pass
        
        return self._search_cpu(text, pattern)

    def _search_gpu_metal(self, text: bytes, pattern: CompiledPattern) -> list[int]:
        """Execute GPU search using Metal"""
        text_length: int = len(text)
        pattern_bytes: bytes = pattern.pattern.encode()
        pattern_length: int = len(pattern_bytes)
        
        # Allocate buffers
        text_buffer: Any = self.device.newBufferWithBytes_length_options_(
            text, text_length, Metal.MTLResourceStorageModeShared
        )
        pattern_buffer: Any = self.device.newBufferWithBytes_length_options_(
            pattern_bytes, pattern_length, Metal.MTLResourceStorageModeShared
        )
        
        # Allocate result buffer (max matches = text length)
        max_matches: int = text_length
        matches_buffer: Any = self.device.newBufferWithLength_options_(
            max_matches * 4, Metal.MTLResourceStorageModeShared
        )
        
        # Match count buffer
        match_count_buffer: Any = self.device.newBufferWithLength_options_(
            4, Metal.MTLResourceStorageModeShared
        )
        match_count_buffer.contents().as_buffer(4)[0:4] = b'\x00\x00\x00\x00'
        
        # Create command buffer and encoder
        command_buffer: Any = self.command_queue.commandBuffer()
        compute_encoder: Any = command_buffer.computeCommandEncoder()
        
        # Set up pipeline
        pipeline_state: Any = self.device.newComputePipelineStateWithFunction_error_(
            pattern.metal_function, None
        )
        compute_encoder.setComputePipelineState_(pipeline_state)
        
        # Set buffers
        compute_encoder.setBuffer_offset_atIndex_(text_buffer, 0, 0)
        compute_encoder.setBuffer_offset_atIndex_(pattern_buffer, 0, 1)
        compute_encoder.setBytes_length_atIndex_(
            (text_length).to_bytes(4, 'little'), 4, 2
        )
        compute_encoder.setBytes_length_atIndex_(
            (pattern_length).to_bytes(4, 'little'), 4, 3
        )
        compute_encoder.setBuffer_offset_atIndex_(matches_buffer, 0, 4)
        compute_encoder.setBuffer_offset_atIndex_(match_count_buffer, 0, 5)
        
        # Dispatch threads
        thread_group_size: int = pipeline_state.maxTotalThreadsPerThreadgroup()
        thread_groups: int = (text_length + thread_group_size - 1) // thread_group_size
        
        compute_encoder.dispatchThreadgroups_threadsPerThreadgroup_(
            Metal.MTLSizeMake(thread_groups, 1, 1),
            Metal.MTLSizeMake(thread_group_size, 1, 1)
        )
        
        compute_encoder.endEncoding()
        command_buffer.commit()
        command_buffer.waitUntilCompleted()
        
        # Read results
        match_count: int = int.from_bytes(
            match_count_buffer.contents().as_buffer(4)[0:4], 'little'
        )
        
        matches: list[int] = []
        if match_count > 0:
            results: bytes = matches_buffer.contents().as_buffer(match_count * 4)
            for i in range(match_count):
                pos: int = int.from_bytes(results[i*4:(i+1)*4], 'little')
                matches.append(pos)
        
        return matches

    def _search_cpu(self, text: bytes, pattern: CompiledPattern) -> list[int]:
        if pattern.regex:
            text_str: str = text.decode('utf-8', errors='ignore')
            return [m.start() for m in pattern.regex.finditer(text_str)]
        else:
            pattern_bytes: bytes = pattern.pattern.encode()
            matches: list[int] = []
            start: int = 0
            
            while True:
                pos: int = text.find(pattern_bytes, start)
                if pos == -1:
                    break
                matches.append(pos)
                start = pos + 1
            
            return matches

    def cleanup(self) -> None:
        # Metal cleanup if needed
        pass

    def __del__(self) -> None:
        self.cleanup()
