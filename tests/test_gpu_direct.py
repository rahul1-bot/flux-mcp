from __future__ import annotations

import tempfile
import time
from pathlib import Path
from flux_mcp.core.metal_accelerator import MetalAccelerator

# Create test file
test_dir: Path = Path(tempfile.mkdtemp(prefix="gpu_test_"))
test_file: Path = test_dir / "large.txt"

# Create large file
print("Creating large test file...")
large_content: str = "\n".join([f"Line {i:05d} " + "x" * 1000 for i in range(1, 15000)])
test_file.write_text(large_content)

print(f"File size: {test_file.stat().st_size / (1024*1024):.2f} MB")

# Test GPU acceleration
accelerator: MetalAccelerator = MetalAccelerator()

# Compile pattern
pattern: str = "Line 05000"
compiled = accelerator.compile_pattern(pattern, is_regex=False)

print(f"\nPattern compiled, is_simple: {compiled.is_simple}")
print(f"Metal function: {compiled.metal_function}")

# Search
content_bytes: bytes = test_file.read_bytes()
print(f"\nSearching for '{pattern}' in {len(content_bytes)} bytes...")

start_time: float = time.time()
matches: list[int] = accelerator.search_gpu(content_bytes, compiled)
end_time: float = time.time()

print(f"Found {len(matches)} matches in {(end_time - start_time) * 1000:.2f} ms")
if matches:
    print(f"First match at position: {matches[0]}")

# Cleanup
import shutil
shutil.rmtree(test_dir)
