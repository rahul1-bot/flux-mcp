from __future__ import annotations

import Metal
import re
from typing import Any
from dataclasses import dataclass
import numpy as np


@dataclass
class CompiledPattern:
    pattern: str
    regex: re.Pattern
    metal_function: Any | None = None
    is_simple: bool = False


class MetalAccelerator:
    def __init__(self) -> None:
        self.device: Any = Metal.MTLCreateSystemDefaultDevice()
        self.command_queue: Any = self.device.newCommandQueue()
        self.library: Any = self._compile_shaders()
        self.pattern_cache: dict[str, CompiledPattern] = {}

    def _compile_shaders(self) -> Any:
        shader_source: str = """
        #include <metal_stdlib>
        using namespace metal;

        kernel void pattern_match(
            const device char* text [[buffer(0)]],
            const device char* pattern [[buffer(1)]],
            device int* results [[buffer(2)]],
            constant uint& text_length [[buffer(3)]],
            constant uint& pattern_length [[buffer(4)]],
            uint id [[thread_position_in_grid]]
        ) {
            if (id >= text_length - pattern_length + 1) {
                return;
            }
            
            bool match = true;
            for (uint i = 0; i < pattern_length; i++) {
                if (text[id + i] != pattern[i]) {
                    match = false;
                    break;
                }
            }
            
            results[id] = match ? 1 : 0;
        }
        
        kernel void regex_match(
            const device char* text [[buffer(0)]],
            const device uint* pattern_states [[buffer(1)]],
            device int* results [[buffer(2)]],
            constant uint& text_length [[buffer(3)]],
            constant uint& state_count [[buffer(4)]],
            uint id [[thread_position_in_grid]]
        ) {
            // Simplified regex matching - to be implemented
            results[id] = 0;
        }
        """
        
        return self.device.newLibraryWithSource_options_error_(
            shader_source, None, None
        )[0]

    def compile_pattern(self, pattern: str, is_regex: bool = False) -> CompiledPattern:
        if pattern in self.pattern_cache:
            return self.pattern_cache[pattern]
        
        compiled: CompiledPattern = CompiledPattern(
            pattern=pattern,
            regex=re.compile(pattern) if is_regex else None,
            is_simple=not is_regex and self._is_simple_pattern(pattern)
        )
        
        if compiled.is_simple:
            compiled.metal_function = self.library.newFunctionWithName_("pattern_match")
        elif is_regex:
            # Complex regex compilation to Metal would go here
            compiled.metal_function = None
        
        self.pattern_cache[pattern] = compiled
        return compiled

    def _is_simple_pattern(self, pattern: str) -> bool:
        # Check if pattern is simple enough for GPU acceleration
        return bool(re.match(r'^[a-zA-Z0-9\s]+$', pattern))

    def search_gpu(self, text: bytes, pattern: CompiledPattern) -> list[int]:
        if not pattern.metal_function:
            return self._search_cpu(text, pattern)
        
        text_array: np.ndarray = np.frombuffer(text, dtype=np.uint8)
        pattern_array: np.ndarray = np.frombuffer(
            pattern.pattern.encode(), dtype=np.uint8
        )
        results_array: np.ndarray = np.zeros(len(text_array), dtype=np.int32)
        
        # Create Metal buffers
        text_buffer: Any = self.device.newBufferWithBytes_length_options_(
            text_array.ctypes.data, len(text_array), 0
        )
        pattern_buffer: Any = self.device.newBufferWithBytes_length_options_(
            pattern_array.ctypes.data, len(pattern_array), 0
        )
        results_buffer: Any = self.device.newBufferWithBytes_length_options_(
            results_array.ctypes.data, results_array.nbytes, 0
        )
        
        # Set up compute pipeline
        pipeline_descriptor: Any = Metal.MTLComputePipelineDescriptor.new()
        pipeline_descriptor.setComputeFunction_(pattern.metal_function)
        
        pipeline_state: Any = self.device.newComputePipelineStateWithDescriptor_error_(
            pipeline_descriptor, None
        )[0]
        
        # Create command buffer
        command_buffer: Any = self.command_queue.commandBuffer()
        encoder: Any = command_buffer.computeCommandEncoder()
        
        encoder.setComputePipelineState_(pipeline_state)
        encoder.setBuffer_offset_atIndex_(text_buffer, 0, 0)
        encoder.setBuffer_offset_atIndex_(pattern_buffer, 0, 1)
        encoder.setBuffer_offset_atIndex_(results_buffer, 0, 2)
        
        text_length: int = len(text_array)
        pattern_length: int = len(pattern_array)
        encoder.setBytes_length_atIndex_(
            text_length, 4, 3
        )
        encoder.setBytes_length_atIndex_(
            pattern_length, 4, 4
        )
        
        # Calculate thread groups
        thread_group_size: int = 256
        thread_groups: int = (text_length + thread_group_size - 1) // thread_group_size
        
        encoder.dispatchThreadgroups_threadsPerThreadgroup_(
            (thread_groups, 1, 1),
            (thread_group_size, 1, 1)
        )
        
        encoder.endEncoding()
        command_buffer.commit()
        command_buffer.waitUntilCompleted()
        
        # Get results
        results_ptr: Any = results_buffer.contents()
        results_array = np.frombuffer(
            results_ptr.as_buffer(results_array.nbytes),
            dtype=np.int32
        )
        
        # Find match positions
        matches: list[int] = []
        for i in range(len(results_array)):
            if results_array[i] == 1:
                matches.append(i)
        
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
