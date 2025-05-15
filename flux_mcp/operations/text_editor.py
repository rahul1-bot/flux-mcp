from __future__ import annotations

import re
import asyncio
from pathlib import Path
from typing import Any, Optional, Union
from dataclasses import dataclass

from flux_mcp.core.transaction_manager import TransactionManager
from flux_mcp.core.memory_manager import MemoryManager
from flux_mcp.parsers import get_parser_for_file


@dataclass
class EditOperation:
    line_number: int
    column: int
    old_text: str
    new_text: str
    

@dataclass
class TextRange:
    start_line: int
    start_column: int
    end_line: int
    end_column: int


class TextEditor:
    def __init__(self, transaction_manager: TransactionManager,
                 memory_manager: MemoryManager) -> None:
        self.transaction_manager: TransactionManager = transaction_manager
        self.memory_manager: MemoryManager = memory_manager
        
    def _validate_python_syntax(self, code: str) -> tuple[bool, str]:
        """Validate Python code syntax using AST parsing.
        
        Args:
            code: Python code to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            import ast
            ast.parse(code)
            return True, ""
        except SyntaxError as e:
            line_content: str = code.splitlines()[e.lineno-1] if e.lineno <= len(code.splitlines()) else ""
            pointer: str = " " * max(0, e.offset-1) + "^" if e.offset else ""
            return False, f"Line {e.lineno}, Col {e.offset}: {e.msg}\n{line_content}\n{pointer}"
            
    def _check_method_signature(self, original: str, replacement: str) -> list[str]:
        """Check method signature compatibility.
        
        Args:
            original: Original method code
            replacement: Replacement method code
            
        Returns:
            List of warning messages for compatibility issues
        """
        warnings: list[str] = []
        
        # Extract method signatures using regex
        import re
        orig_sig = re.search(r'def\s+(\w+)\s*\((.*?)\)', original)
        new_sig = re.search(r'def\s+(\w+)\s*\((.*?)\)', replacement)
        
        if orig_sig and new_sig:
            orig_name: str = orig_sig.group(1)
            new_name: str = new_sig.group(1)
            
            # Extract parameter lists
            orig_params: list[str] = [
                p.split(':')[0].split('=')[0].strip() 
                for p in orig_sig.group(2).split(',') 
                if p.strip()
            ]
            
            new_params: list[str] = [
                p.split(':')[0].split('=')[0].strip() 
                for p in new_sig.group(2).split(',') 
                if p.strip()
            ]
            
            # Check for removed parameters
            for param in orig_params:
                if param not in new_params and param not in ['self', 'cls']:
                    warnings.append(f"Parameter '{param}' removed - this may break code that calls this method")
            
            # Check for added required parameters (no default value)
            for i, param in enumerate(new_params):
                if param not in orig_params:
                    # Check if parameter has default value
                    param_section: str = new_sig.group(2).split(',')[i]
                    if '=' not in param_section and param not in ['self', 'cls']:
                        warnings.append(f"Required parameter '{param}' added - this will break existing code")
        
        return warnings

    async def replace(self, file_path: Path, old_text: str, new_text: str,
                     is_regex: bool = False, all_occurrences: bool = True) -> int:
        # Read file content
        content: str = await self._read_file_content(file_path)
        
        # Perform replacements
        if is_regex:
            pattern: re.Pattern = re.compile(old_text)
            if all_occurrences:
                new_content: str
                count: int
                new_content, count = pattern.subn(new_text, content)
            else:
                match: re.Match | None = pattern.search(content)
                if match:
                    new_content = content[:match.start()] + new_text + content[match.end():]
                    count = 1
                else:
                    new_content = content
                    count = 0
        else:
            if all_occurrences:
                new_content = content.replace(old_text, new_text)
                count = content.count(old_text)
            else:
                pos: int = content.find(old_text)
                if pos != -1:
                    new_content = content[:pos] + new_text + content[pos + len(old_text):]
                    count = 1
                else:
                    new_content = content
                    count = 0
        
        # Write back if changed
        if count > 0:
            await self._write_file_content(file_path, new_content)
        
        return count

    async def insert_text(self, file_path: Path, line_number: int, 
                         column: int, text: str) -> None:
        lines: list[str] = await self._read_file_lines(file_path)
        
        # Validate line number
        if line_number < 0 or line_number >= len(lines):
            raise ValueError(f"Invalid line number: {line_number}")
        
        line: str = lines[line_number]
        
        # Validate column
        if column < 0 or column > len(line):
            raise ValueError(f"Invalid column: {column}")
        
        # Insert text
        new_line: str = line[:column] + text + line[column:]
        lines[line_number] = new_line
        
        # Write back
        await self._write_file_lines(file_path, lines)

    async def delete_range(self, file_path: Path, text_range: TextRange) -> str:
        lines: list[str] = await self._read_file_lines(file_path)
        
        # Validate range
        if text_range.start_line < 0 or text_range.end_line >= len(lines):
            raise ValueError("Invalid line range")
        
        # Extract deleted text
        deleted_text: str = ""
        
        if text_range.start_line == text_range.end_line:
            # Single line deletion
            line: str = lines[text_range.start_line]
            deleted_text = line[text_range.start_column:text_range.end_column]
            new_line: str = line[:text_range.start_column] + line[text_range.end_column:]
            lines[text_range.start_line] = new_line
        else:
            # Multi-line deletion
            for i in range(text_range.start_line, text_range.end_line + 1):
                if i == text_range.start_line:
                    deleted_text += lines[i][text_range.start_column:] + '\n'
                    lines[i] = lines[i][:text_range.start_column]
                elif i == text_range.end_line:
                    deleted_text += lines[i][:text_range.end_column]
                    lines[i] = lines[i][text_range.end_column:]
                else:
                    deleted_text += lines[i] + '\n'
                    lines[i] = ""
            
            # Merge first and last lines
            lines[text_range.start_line] += lines[text_range.end_line]
            
            # Remove empty lines in between
            del lines[text_range.start_line + 1:text_range.end_line + 1]
        
        # Write back
        await self._write_file_lines(file_path, lines)
        
        return deleted_text

    async def duplicate_lines(self, file_path: Path, start_line: int, 
                            end_line: int) -> None:
        lines: list[str] = await self._read_file_lines(file_path)
        
        # Validate range
        if start_line < 0 or end_line >= len(lines) or start_line > end_line:
            raise ValueError("Invalid line range")
        
        # Duplicate lines
        duplicated: list[str] = lines[start_line:end_line + 1]
        lines[end_line + 1:end_line + 1] = duplicated
        
        # Write back
        await self._write_file_lines(file_path, lines)

    async def move_lines(self, file_path: Path, start_line: int, 
                        end_line: int, target_line: int) -> None:
        lines: list[str] = await self._read_file_lines(file_path)
        
        # Validate range
        if start_line < 0 or end_line >= len(lines) or start_line > end_line:
            raise ValueError("Invalid line range")
        
        if target_line < 0 or target_line > len(lines):
            raise ValueError("Invalid target line")
        
        # Extract lines to move
        moving_lines: list[str] = lines[start_line:end_line + 1]
        
        # Remove from original position
        del lines[start_line:end_line + 1]
        
        # Adjust target if necessary
        if target_line > start_line:
            target_line -= (end_line - start_line + 1)
        
        # Insert at new position
        lines[target_line:target_line] = moving_lines
        
        # Write back
        await self._write_file_lines(file_path, lines)

    async def transform_text(self, file_path: Path, transformation: str) -> None:
        content: str = await self._read_file_content(file_path)
        
        if transformation == "uppercase":
            new_content: str = content.upper()
        elif transformation == "lowercase":
            new_content: str = content.lower()
        elif transformation == "title":
            new_content: str = content.title()
        elif transformation == "capitalize":
            new_content: str = content.capitalize()
        else:
            raise ValueError(f"Unknown transformation: {transformation}")
        
        await self._write_file_content(file_path, new_content)

    async def trim_whitespace(self, file_path: Path, mode: str = "trailing") -> None:
        lines: list[str] = await self._read_file_lines(file_path)
        
        if mode == "trailing":
            lines = [line.rstrip() for line in lines]
        elif mode == "leading":
            lines = [line.lstrip() for line in lines]
        elif mode == "both":
            lines = [line.strip() for line in lines]
        else:
            raise ValueError(f"Unknown trim mode: {mode}")
        
        await self._write_file_lines(file_path, lines)
        
    async def text_replace(self, file_path: Path, highlight: Union[str, dict[str, Any]], 
                          replace_with: str, checkpoint: Optional[str] = None, 
                          auto_checkpoint: bool = False) -> str:
        """Advanced text replacement using hierarchical selection.
        
        Args:
            file_path: Path to the file
            highlight: Target specification in format "ClassName" or "ClassName.method_name" 
                     DO NOT include 'class' or 'def' keywords, parentheses, or colons
            replace_with: Replacement text (triple quotes recommended)
            checkpoint: Optional name for the checkpoint
            auto_checkpoint: Whether to auto-generate a checkpoint name
        
        Returns:
            Success message
        """
        # Check if file exists
        if not file_path.exists():
            raise ValueError(f"File not found: {file_path}")
            
        # Detect file encoding and line endings
        try:
            import chardet
            with open(file_path, 'rb') as f:
                sample = f.read(4096)
                encoding_result = chardet.detect(sample)
                encoding = encoding_result['encoding'] or 'utf-8'
                
                # Check line endings
                crlf_count = sample.count(b'\r\n')
                lf_count = sample.count(b'\n') - crlf_count
                line_ending = '\r\n' if crlf_count > lf_count else '\n'
        except (ImportError, Exception):
            encoding = 'utf-8'
            line_ending = '\n'
        
        # Normalize replacement line endings to match the file
        if '\n' in replace_with and line_ending != '\n':
            replace_with = replace_with.replace('\n', line_ending)
            
        # Perform basic validation on highlight parameter
        if isinstance(highlight, str):
            # Common mistake: including class/def keywords
            if highlight.startswith("class ") or highlight.startswith("def "):
                raise ValueError(
                    "HIGHLIGHT FORMAT ERROR: Do not include 'class' or 'def' keywords in highlight parameter.\n"
                    f"  INCORRECT: '{highlight}'\n"
                    f"  CORRECT: '{highlight.split()[1].rstrip(':').rstrip('()')}"
                )
            
            # Common mistake: including parentheses or colons  
            if "(" in highlight or ":" in highlight:
                clean_highlight = highlight.split("(")[0].rstrip(":")
                raise ValueError(
                    "HIGHLIGHT FORMAT ERROR: Do not include parentheses or colons in highlight parameter.\n"
                    f"  INCORRECT: '{highlight}'\n"
                    f"  CORRECT: '{clean_highlight}'"
                )
        
        # Check for triple quotes in replacement text
        if not (replace_with.startswith('"""') or replace_with.startswith("'''")) and '\n' in replace_with:
            raise ValueError(
                "REPLACEMENT TEXT ERROR: Multi-line replacement text should use triple quotes to preserve indentation.\n"
                "Example: replace_with=\"\"\"def method():\\n    return True\"\"\""
            )
            
        # Validate replacement content for common definition errors
        if isinstance(highlight, str) and "." in highlight and '\n' in replace_with:
            # This is a method replacement - should start with def/async def
            method_name = highlight.split(".")[-1]
            first_line = replace_with.strip().split('\n')[0].strip()
            
            if not (first_line.startswith("def ") or first_line.startswith("async def ")):
                raise ValueError(
                    f"REPLACEMENT CONTENT ERROR: When replacing method '{method_name}', the replacement text must start with 'def {method_name}' or 'async def {method_name}'.\n"
                    "Include the full method definition line."
                )
                
            if method_name not in first_line:
                raise ValueError(
                    f"REPLACEMENT CONTENT ERROR: Method name mismatch. Replacing '{method_name}' but replacement defines a different method name in: '{first_line}'.\n"
                    f"Method names must match."
                )
        
        # Get original content
        content: str = await self._read_file_content(file_path)
        
        # Start transaction
        transaction_id: str = await self.transaction_manager.begin()
        
        try:
            # Acquire lock to prevent concurrent modifications
            await self.transaction_manager.acquire_file_lock(transaction_id, file_path)
            
            # Create checkpoint if requested
            if checkpoint or auto_checkpoint:
                checkpoint_name: str = checkpoint or f"text_replace_{file_path.name}_{transaction_id[:8]}"
                await self.transaction_manager.create_checkpoint(transaction_id, file_path, checkpoint_name)
            
            # Get the appropriate parser based on file extension
            parser = get_parser_for_file(file_path)
            
            # Parse the highlight pattern to find the target
            result = parser.find_target(content, highlight)
            
            # Set line ending in result for preservation
            result.line_ending = line_ending
            
            # Get original block for method signature compatibility check
            original_block: str = content[result.start_pos:result.end_pos]
            
            # Check for method signature compatibility if this is a method replacement
            if isinstance(highlight, str) and "." in highlight and file_path.suffix.lower() == '.py':
                compatibility_warnings: list[str] = self._check_method_signature(original_block, replace_with)
                if compatibility_warnings:
                    warning_str: str = "\n- ".join(compatibility_warnings)
                    print(f"⚠️ WARNING: Method signature changes detected:\n- {warning_str}")
            
            # Pre-validate replacement text syntax if it's a Python file
            if file_path.suffix.lower() == '.py':
                is_valid: bool
                error_msg: str
                is_valid, error_msg = self._validate_python_syntax(replace_with)
                if not is_valid:
                    return f"⚠️ SYNTAX ERROR in replacement code: {error_msg}\nNo changes applied."

            # Check if replacement has inconsistent indentation
            replacement_lines = replace_with.splitlines()
            if len(replacement_lines) > 1:
                indentation_chars = []
                for line in replacement_lines[1:]:  # Skip first line
                    if line.strip():  # Only non-empty lines
                        leading_whitespace = line[:len(line) - len(line.lstrip())]
                        if leading_whitespace:
                            indentation_chars.append('\t' if '\t' in leading_whitespace else ' ')
                
                # If we have both tabs and spaces for indentation, warn the user
                if ' ' in indentation_chars and '\t' in indentation_chars:
                    return f"WARNING: Mixed indentation (tabs and spaces) detected in replacement text. "\
                           f"The tool will attempt to fix this, but please use consistent indentation for best results."
            
            # Apply the replacement while preserving formatting
            new_content: str = parser.apply_replacement(content, result, replace_with)
            
            # Validate the resulting content for syntax errors (for Python files)
            if file_path.suffix.lower() == '.py':
                is_valid: bool
                error_msg: str
                is_valid, error_msg = self._validate_python_syntax(new_content)
                if not is_valid:
                    return f"⚠️ ERROR: The replacement would create invalid Python: {error_msg}\nChanges NOT applied."
            
            # Write the modified content with original encoding
            await self.transaction_manager.write_to_temp(
                transaction_id, file_path, new_content.encode(encoding, errors='replace')
            )
            
            # Commit the transaction
            await self.transaction_manager.commit(transaction_id)
            
            return f"✓ Successfully replaced content in {file_path}"
            
        except Exception as e:
            # Rollback on any error
            await self.transaction_manager.rollback(transaction_id)
            raise ValueError(f"Failed to replace text: {str(e)}")

    async def _read_file_content(self, file_path: Path) -> str:
        """Read file content with encoding detection."""
        # Import chardet if available
        try:
            import chardet
            with open(file_path, 'rb') as f:
                raw_data = f.read(4096)
                encoding_result = chardet.detect(raw_data)
                
            encoding = encoding_result['encoding'] or 'utf-8'
        except (ImportError, Exception):
            encoding = 'utf-8'  # Default to UTF-8 if detection fails
        
        # Read with detected encoding
        with open(file_path, 'r', encoding=encoding, errors='replace') as f:
            return f.read()

    async def _read_file_lines(self, file_path: Path) -> list[str]:
        content: str = await self._read_file_content(file_path)
        return content.splitlines(keepends=True)

    async def _write_file_content(self, file_path: Path, content: str) -> None:
        # Use transaction manager for atomic writes
        transaction_id: str = await self.transaction_manager.begin()
        
        try:
            await self.transaction_manager.acquire_file_lock(transaction_id, file_path)
            await self.transaction_manager.write_to_temp(
                transaction_id, file_path, content.encode('utf-8')
            )
            await self.transaction_manager.commit(transaction_id)
        except Exception as e:
            await self.transaction_manager.rollback(transaction_id)
            raise e

    async def _write_file_lines(self, file_path: Path, lines: list[str]) -> None:
        content: str = ''.join(lines)
        await self._write_file_content(file_path, content)
