from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from dataclasses import dataclass, field
import re


@dataclass
class ParserResult:
    start_pos: int
    end_pos: int
    indentation: str
    decorators: list[str] = field(default_factory=list)
    comments_before: list[str] = field(default_factory=list)
    comments_after: list[str] = field(default_factory=list)
    line_ending: str = '\n'
    metadata: dict[str, Any] = field(default_factory=dict)
    parent_indentation: str = ""  # Track parent block indentation


class BaseParser(ABC):
    def __init__(self) -> None:
        self.content: str = ""
    
    @abstractmethod
    def find_target(self, content: str, highlight: str | dict[str, Any]) -> ParserResult:
        """Find the target in content based on highlight specification."""
        pass
    
    @abstractmethod
    def apply_replacement(self, content: str, result: ParserResult, replace_with: str) -> str:
        """Apply replacement maintaining proper formatting."""
        pass
    
    def preserve_indentation(self, original_block: str, new_text: str, tab_width: int = 4) -> str:
        """Preserve indentation pattern from original block in the new text.

        This carefully maintains the indentation structure from the original
        code when applying replacements, which is critical for Python.

        Args:
        original_block: Original text block with existing indentation
        new_text: New text to apply indentation to
        tab_width: Number of spaces equivalent to one tab (default: 4)

        Returns:
        Properly indented new text
        """
        if not original_block.strip() or not new_text.strip():
            return new_text

        # Get lines from both blocks
        original_lines: list[str] = original_block.splitlines()
        new_lines: list[str] = new_text.splitlines()
        
        # Find the indentation of the first line in the original block
        base_indent: str = ""
        for line in original_lines:
            if line.strip():
                base_indent = line[:len(line) - len(line.lstrip())]
                break
                
        if not base_indent:
            return new_text
        
        # Detect if original code uses tabs or spaces
        uses_tabs: bool = '\t' in base_indent
        indent_char: str = '\t' if uses_tabs else ' '
        
        # Calculate space equivalence (only relevant for comparison)
        base_indent_spaces: int = len(base_indent.replace('\t', ' ' * tab_width))
        
        # Special case for empty methods with just 'pass'
        if 'pass' in new_text and len(new_text.strip().splitlines()) <= 2:
            # Simple pass statement case
            if new_text.strip() == 'pass':
                return base_indent + indent_char + 'pass'
                
            # Method with just pass
            if re.match(r'def\s+\w+\s*\(.*\)\s*:\s*pass', new_text.strip()):
                def_line = new_text.strip().split('pass')[0].rstrip()
                one_level = indent_char if uses_tabs else (indent_char * tab_width)
                return base_indent + def_line + '\n' + base_indent + one_level + 'pass'
            
        # Analyze the original code's indentation pattern
        indent_patterns = {}
        for line in original_lines:
            if line.strip():
                spaces = len(line) - len(line.lstrip())
                if spaces > 0:
                    style = line[:spaces]
                    if style not in indent_patterns:
                        indent_patterns[style] = 0
                    indent_patterns[style] += 1
        
        # Use the most common indentation style for consistency
        most_common_indent = base_indent
        if indent_patterns:
            try:
                most_common_indent = max(indent_patterns.items(), key=lambda x: x[1])[0]
            except:
                pass
            
        # Process the new text with proper indentation
        result_lines: list[str] = []
        
        # Process first line (usually function/class definition)
        if new_lines and new_lines[0].strip():
            if any(new_lines[0].lstrip().startswith(prefix) for prefix in ['def ', 'class ', 'async def']):
                # This is a function/class definition, use base indentation
                result_lines.append(base_indent + new_lines[0].lstrip())
            else:
                # For other lines, use base indentation + one level
                one_level: str = indent_char if uses_tabs else (indent_char * tab_width)
                result_lines.append(base_indent + one_level + new_lines[0].lstrip())
        
        # Process remaining lines with smart indentation tracking
        # First, analyze the indentation structure of the new text
        line_depths = self._analyze_line_depths(new_lines)
        
        # Process remaining lines using relative indentation based on line depths
        for i, line in enumerate(new_lines[1:], 1):
            if not line.strip():
                result_lines.append("")  # Empty line
                continue
                
            depth = line_depths.get(i, 1)  # Default to depth 1 if unknown
            
            if uses_tabs:
                indent = base_indent + indent_char * depth
            else:
                indent = base_indent + (indent_char * tab_width * depth)
                
            result_lines.append(indent + line.lstrip())
        
        return '\n'.join(result_lines)
        
    def _analyze_line_depths(self, lines: list[str]) -> dict[int, int]:
        """Analyze the logical nesting depth of each line in code."""
        depths = {}
        current_depth = 0
        indent_stack = []
        
        for i, line in enumerate(lines):
            if not line.strip():
                continue
                
            # Count leading whitespace
            leading_space = len(line) - len(line.lstrip())
            
            # Adjust depth based on indentation
            if not indent_stack:
                indent_stack.append(leading_space)
                depths[i] = 0  # First non-empty line is at depth 0
            elif leading_space > indent_stack[-1]:
                indent_stack.append(leading_space)
                current_depth += 1
                depths[i] = current_depth
            elif leading_space < indent_stack[-1]:
                # Find matching indentation level
                while indent_stack and leading_space < indent_stack[-1]:
                    indent_stack.pop()
                    current_depth -= 1
                
                if not indent_stack or leading_space > indent_stack[-1]:
                    # If we couldn't find matching indent, reset
                    indent_stack = [leading_space]
                    current_depth = 0
                
                depths[i] = current_depth
            else:
                # Same indentation as previous line
                depths[i] = current_depth
                
        return depths