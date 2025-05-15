from __future__ import annotations

import re
from typing import Any, Union, Optional

from .base_parser import BaseParser, ParserResult


class LaTeXParser(BaseParser):
    def __init__(self) -> None:
        super().__init__()
        
    def find_target(self, content: str, highlight: str | dict[str, Any]) -> ParserResult:
        self.content = content
        
        # Simple section or environment selection
        if isinstance(highlight, str):
            if ":" in highlight:
                # Pattern like "section:Introduction" or "equation:main_formula"
                env_type, name = highlight.split(":", 1)
                return self._find_section_or_environment(env_type, name)
            else:
                # Just a simple environment name
                return self._find_environment(highlight)
        
        # Complex selection with block
        if isinstance(highlight, dict):
            if "target" in highlight:
                if isinstance(highlight["target"], list):
                    # Multiple targets not supported yet - use the first one
                    target: str = highlight["target"][0]
                else:
                    target = highlight["target"]
                
                # Parse the target
                if ":" in target:
                    env_type, name = target.split(":", 1)
                    result: ParserResult = self._find_section_or_environment(env_type, name)
                else:
                    result = self._find_environment(target)
                
                # If block_start and block_end are specified, narrow down the selection
                if "block_start" in highlight and "block_end" in highlight:
                    return self._find_block(
                        result, 
                        highlight["block_start"], 
                        highlight["block_end"],
                        highlight.get("match_type", "exact")
                    )
                
                return result
        
        raise ValueError(f"Invalid highlight format: {highlight}")
    
    def apply_replacement(self, content: str, result: ParserResult, replace_with: str) -> str:
        # Get the original block to preserve indentation
        original_block: str = content[result.start_pos:result.end_pos]
        
        # Ensure replacement has proper indentation
        formatted_replacement: str = self.preserve_indentation(original_block, replace_with)
        
        # Apply the replacement
        new_content: str = content[:result.start_pos] + formatted_replacement + content[result.end_pos:]
        return new_content
        
    def _list_available_sections(self, env_type: str, limit: int = 5) -> str:
        """List available sections/environments of a specific type for error messages.
        
        Args:
            env_type: Type of section or environment to find
            limit: Maximum number of items to list
            
        Returns:
            Comma-separated list of found items
        """
        found_items: list[str] = []
        lines: list[str] = self.content.splitlines()
        
        if env_type in ["section", "subsection", "chapter", "subsubsection", "paragraph"]:
            # Look for sections, chapters, etc.
            pattern: str = r'\\' + re.escape(env_type) + r'\{([^}]+)\}'
            for line in lines:
                matches = re.findall(pattern, line)
                found_items.extend(matches)
        else:
            # Look for environments
            begin_pattern: str = r'\\begin\{' + re.escape(env_type) + r'\}(?:\[([^]]+)\])?'
            for line in lines:
                matches = re.findall(begin_pattern, line)
                # Extract label if present, otherwise just note the environment
                if matches:
                    for match in matches:
                        if match:  # Has a label
                            found_items.append(match)
                        else:
                            found_items.append(f"<unlabeled {env_type}>")
        
        # Limit the number of items and format
        if not found_items:
            return "none found"
        
        limited_items: list[str] = found_items[:limit]
        if len(found_items) > limit:
            return ", ".join(limited_items) + f", and {len(found_items) - limit} more"
        else:
            return ", ".join(limited_items)