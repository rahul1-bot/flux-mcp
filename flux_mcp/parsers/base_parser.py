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

        ENHANCED: This is a critical function for Python code replacement that carefully 
        maintains the indentation structure necessary for proper code function.

        Args:
        original_block: Original text block with existing indentation
        new_text: New text to apply indentation to
        tab_width: Number of spaces equivalent to one tab (default: 4)

        Returns:
        Properly indented new text that maintains Python's hierarchical structure
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
        
        # Determine if the replacement uses different indentation style 
        # (tabs vs spaces) and needs conversion
        new_base_indent: str = ""
        for line in new_lines:
            if line.strip():
                new_base_indent = line[:len(line) - len(line.lstrip())]
                break
                
        new_uses_tabs: bool = False
        if new_base_indent:
            new_uses_tabs = '\t' in new_base_indent
        
        # Handle mixed indentation (halt with error if detected)
        for line in new_lines:
            if line.strip():
                indent = line[:len(line) - len(line.lstrip())]
                if '\t' in indent and ' ' in indent and indent.strip():
                    raise ValueError(
                        "CRITICAL ERROR: Mixed tab and space indentation detected in replacement code.\n"
                        "Python requires consistent indentation. Use either tabs OR spaces, never both."
                    )
        
        # Early exit for special cases (single line replacements)
        if len(new_lines) <= 1:
            if not new_lines:
                return ""
            return base_indent + new_lines[0].lstrip()
        
        # Special case for empty methods with just 'pass'
        if len(new_lines) <= 2 and any('pass' in line for line in new_lines):
            # Method with just pass
            first_line: str = new_lines[0]
            if re.match(r'def\s+\w+\s*\(.*\)\s*:', first_line.strip()):
                one_level = indent_char if uses_tabs else (indent_char * tab_width)
                return base_indent + first_line.lstrip() + '\n' + base_indent + one_level + 'pass'
            elif first_line.strip() == 'pass':
                return base_indent + indent_char + 'pass'
                
        # Indentation conversion if styles don't match (very important to standardize)
        if uses_tabs != new_uses_tabs and new_base_indent:
            # Need to convert indentation styles
            converted_lines: list[str] = []
            for line in new_lines:
                if not line.strip():  # Skip blank lines
                    converted_lines.append(line)
                    continue
                    
                # Calculate equivalent indentation
                current_indent: str = line[:len(line) - len(line.lstrip())]
                if new_uses_tabs and not uses_tabs:
                    # Convert tabs to spaces
                    indent_level: int = current_indent.count('\t')
                    # Remove any existing tabs and add proper space indentation
                    new_indent: str = ' ' * (indent_level * tab_width)
                    converted_lines.append(new_indent + line.lstrip())
                elif not new_uses_tabs and uses_tabs:
                    # Convert spaces to tabs
                    # Calculate space groups
                    space_count: int = current_indent.count(' ')
                    indent_level: int = space_count // tab_width
                    # Remove existing spaces and add proper tab indentation
                    new_indent: str = '\t' * indent_level
                    converted_lines.append(new_indent + line.lstrip())
                    
            # Replace new_lines with converted lines for further processing
            new_lines = converted_lines
        
        # CRITICAL: Validate indentation hierarchy consistency
        # Check that deeper blocks maintain their relationship to parent blocks
        indentation_errors: list[dict[str, Any]] = []
        if len(new_lines) > 1:
            # Extract blocks structure (if, for, while, def, class, etc)
            block_starters: list[int] = []
            block_structure: dict[int, dict[str, Any]] = {}
            
            # First pass - identify blocks and their indentation requirements
            for i, line in enumerate(new_lines):
                stripped: str = line.strip()
                if not stripped:
                    continue
                    
                # Check if this is a block-starting line (ends with colon)
                if stripped.endswith(':') and not stripped.startswith('#'):
                    # This line starts a new block
                    block_starters.append(i)
                    block_structure[i] = {
                        "indent_level": len(line) - len(line.lstrip()),
                        "requires_indent": True,
                        "children": []
                    }
            
            # Second pass - validate block child indentation
            for block_start in block_starters:
                block_info = block_structure[block_start]
                block_indent = block_info["indent_level"]
                
                # Look at the next line after the block starter
                if block_start + 1 < len(new_lines):
                    next_line = new_lines[block_start + 1].rstrip()
                    if next_line.strip():  # If not empty
                        next_indent = len(next_line) - len(next_line.lstrip())
                        
                        # Python requires block contents to be indented deeper than the block starter
                        if next_indent <= block_indent:
                            # This is an indentation hierarchy error
                            indentation_errors.append({
                                "line_number": block_start + 2,  # 1-indexed for human readability
                                "parent_line_number": block_start + 1,
                                "parent_line": new_lines[block_start].strip(),
                                "line_content": next_line,
                                "error_type": "INVALID_BLOCK_STRUCTURE",
                                "message": f"Line after block definition must be indented. Block starts with '{new_lines[block_start].strip()}'",
                                "suggestion": "Indent the line after any line ending with ':' in Python"
                            })
            
            # If indentation hierarchy errors were found, raise an exception
            if indentation_errors:
                error_msg = "CRITICAL INDENTATION HIERARCHY ERROR:\n\n"
                
                for i, error in enumerate(indentation_errors, 1):
                    error_msg += f"ERROR #{i}: {error['error_type']} - {error['message']}\n"
                    error_msg += f"Block starts at line {error['parent_line_number']}: {error['parent_line']}\n"
                    error_msg += f"Invalid indentation at line {error['line_number']}: {error['line_content']}\n"
                    error_msg += f"Suggestion: {error['suggestion']}\n\n"
                
                error_msg += "\nPython requires consistent indentation hierarchy. Block contents must be indented deeper than the block starter."
                raise ValueError(error_msg)
        
        # Process the new text with proper hierarchical indentation
        result_lines: list[str] = []
        
        # Determine the base indentation level of the new text (first non-empty line)
        new_base_level: int = 0
        for line in new_lines:
            if line.strip():
                new_indent: str = line[:len(line) - len(line.lstrip())]
                if uses_tabs:
                    new_base_level = new_indent.count('\t')
                else:
                    new_base_level = new_indent.count(' ') // tab_width
                break
        
        # Process all lines maintaining relative indentation hierarchy
        for i, line in enumerate(new_lines):
            if not line.strip():
                result_lines.append("")  # Keep empty lines as-is
                continue
                
            # Calculate relative indentation from the base of new text
            current_indent: str = line[:len(line) - len(line.lstrip())]
            if uses_tabs:
                current_level: int = current_indent.count('\t')
                relative_level: int = max(0, current_level - new_base_level)
                final_indent: str = base_indent + indent_char * relative_level
            else:
                current_spaces: int = current_indent.count(' ')
                current_level: int = current_spaces // tab_width
                relative_level: int = max(0, current_level - new_base_level) 
                final_indent: str = base_indent + (indent_char * tab_width) * relative_level
            
            # Apply the calculated indentation
            result_lines.append(final_indent + line.lstrip())
        
        return '\n'.join(result_lines)
        
    def _analyze_line_depths(self, lines: list[str]) -> dict[int, int]:
        """
        Analyze the logical nesting depth of each line in Python code.
        Enhanced to handle complex indentation patterns more accurately.
        
        Args:
            lines: List of code lines
            
        Returns:
            Dictionary mapping line indexes to their logical depth
        """
        depths: dict[int, int] = {}
        current_depth: int = 0
        indent_stack: list[int] = []
        
        # First pass: determine indentation units
        indent_sizes: list[int] = []
        for line in lines:
            if line.strip():
                leading_space: int = len(line) - len(line.lstrip())
                if leading_space > 0:
                    indent_sizes.append(leading_space)
        
        # Detect indentation increment if possible
        indent_increment: int = 4  # Default
        if len(indent_sizes) >= 2:
            sorted_sizes: list[int] = sorted(set(indent_sizes))
            if len(sorted_sizes) >= 2:
                increments: list[int] = [sorted_sizes[i] - sorted_sizes[i-1] for i in range(1, len(sorted_sizes))]
                if increments:
                    # Try to find a consistent increment 
                    from collections import Counter
                    increment_counts = Counter(increments)
                    most_common = increment_counts.most_common(1)
                    if most_common:
                        indent_increment = most_common[0][0]
        
        # Second pass: analyze hierarchical depths
        for i, line in enumerate(lines):
            if not line.strip():
                continue
                
            # Count leading whitespace
            leading_space: int = len(line) - len(line.lstrip())
            
            # First significant line establishes baseline
            if not indent_stack:
                indent_stack.append(leading_space)
                depths[i] = 0
                continue
            
            # Determine relative position
            if leading_space > indent_stack[-1]:
                # Indented deeper - going down one or more levels
                indent_levels_deeper: int = (leading_space - indent_stack[-1]) // max(1, indent_increment)
                # Safety check to prevent excessively deep nesting
                if indent_levels_deeper > 5:  # Unusual in normal Python code
                    indent_levels_deeper = 1  # Cap to reasonable level
                
                indent_stack.append(leading_space)
                current_depth += indent_levels_deeper
                depths[i] = current_depth
            elif leading_space < indent_stack[-1]:
                # Dedented - going up one or more levels
                while indent_stack and leading_space < indent_stack[-1]:
                    indent_stack.pop()
                    current_depth = max(0, current_depth - 1)
                
                # Handle case where we've dedented to a level not seen before
                if not indent_stack or leading_space > indent_stack[-1]:
                    indent_stack.append(leading_space)
                
                depths[i] = current_depth
            else:
                # Same level
                depths[i] = current_depth
                
        return depths