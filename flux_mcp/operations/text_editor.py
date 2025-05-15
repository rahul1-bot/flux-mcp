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
        """Rigorous Python code syntax validation with AST parsing.
        
        Performs comprehensive syntax checking including:
        - AST parsing to catch any syntax errors
        - Feature detection for Python version compatibility
        - Common code smells and potential issues
        
        Args:
            code: Python code to validate
            
        Returns:
            Tuple of (is_valid, detailed_error_message)
        """
        # Basic syntax validation
        try:
            import ast
            ast_tree = ast.parse(code)
        except SyntaxError as e:
            # Enhanced error reporting with exact location and visualization
            line_content: str = ""
            pointer: str = ""
            if e.lineno <= len(code.splitlines()):
                line_content = code.splitlines()[e.lineno-1]
                if e.offset:
                    pointer = " " * max(0, e.offset-1) + "^" * min(5, len(line_content) - e.offset + 1)
            
            detailed_error = (
                f"CRITICAL SYNTAX ERROR: {e.msg}\n"
                f"Line {e.lineno}, Column {e.offset}:\n"
                f"{line_content}\n"
                f"{pointer}\n\n"
                f"This code contains invalid Python syntax and would fail to execute."
            )
            return False, detailed_error
        except Exception as e:
            return False, f"CRITICAL PARSING ERROR: {str(e)}"
        
        # Advanced feature detection for version compatibility
        compatibility_issues: list[dict[str, Any]] = []
        
        try:
            import sys
            import re
            import builtins
            import platform
            
            # Detect current Python version
            current_python_version = tuple(map(int, platform.python_version_tuple()))
            
            # Feature compatibility checks
            incompatible_features = []
            
            # 1. Check for f-strings (Python 3.6+)
            if re.search(r'f[\'"]', code):
                if current_python_version < (3, 6):
                    incompatible_features.append({
                        "feature": "f-strings", 
                        "min_version": "3.6",
                        "line_numbers": [i+1 for i, line in enumerate(code.splitlines()) if re.search(r'f[\'"]', line)]
                    })
            
            # 2. Check for walrus operator := (Python 3.8+)
            if re.search(r':=', code):
                if current_python_version < (3, 8):
                    incompatible_features.append({
                        "feature": "assignment expressions (walrus operator :=)", 
                        "min_version": "3.8",
                        "line_numbers": [i+1 for i, line in enumerate(code.splitlines()) if ":=" in line]
                    })
                    
            # 3. Check for match/case syntax (Python 3.10+)
            if re.search(r'\bmatch\b.*?:', code) and re.search(r'\bcase\b.*?:', code):
                if current_python_version < (3, 10):
                    incompatible_features.append({
                        "feature": "match/case pattern matching", 
                        "min_version": "3.10",
                        "line_numbers": [i+1 for i, line in enumerate(code.splitlines()) 
                                       if re.search(r'\bmatch\b.*?:', line) or re.search(r'\bcase\b.*?:', line)]
                    })
            
            # 4. Check for union operator | in type hints (Python 3.10+)
            if re.search(r':\s*\w+\s*\|\s*\w+', code):
                if current_python_version < (3, 10):
                    incompatible_features.append({
                        "feature": "union type operator |", 
                        "min_version": "3.10",
                        "line_numbers": [i+1 for i, line in enumerate(code.splitlines()) 
                                       if re.search(r':\s*\w+\s*\|\s*\w+', line)]
                    })
                    
            # 5. Check for positional-only parameters (Python 3.8+)
            if re.search(r'\([^)]*/, ', code):
                if current_python_version < (3, 8):
                    incompatible_features.append({
                        "feature": "positional-only parameters", 
                        "min_version": "3.8",
                        "line_numbers": [i+1 for i, line in enumerate(code.splitlines()) if re.search(r'\([^)]*/, ', line)]
                    })
                    
            # Format incompatibility report
            if incompatible_features:
                error_msg = "PYTHON VERSION COMPATIBILITY ISSUES:\n\n"
                for i, feature in enumerate(incompatible_features, 1):
                    error_msg += (f"{i}. The code uses {feature['feature']} which requires Python {feature['min_version']}+\n"
                                f"   Found at line(s): {', '.join(map(str, feature['line_numbers']))}\n\n")
                error_msg += f"Current Python version: {'.'.join(map(str, current_python_version))}\n\n"
                error_msg += "These features may cause runtime errors if run on older Python versions."
                compatibility_issues.append({"message": error_msg, "is_critical": False})
        
        except Exception as e:
            # Non-critical - version compatibility check failed but syntax is still valid
            compatibility_issues.append({
                "message": f"Failed to check Python version compatibility: {str(e)}",
                "is_critical": False
            })
            
        # Advanced code quality checks
        try:
            # AST-based static analysis
            code_issues: list[dict[str, Any]] = []
            
            # Track variable definitions and usage for basic type checking
            defined_vars: dict[str, list[ast.AST]] = {}
            
            # Analyze the AST
            for node in ast.walk(ast_tree):
                # Check for undefined variables
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    var_name = node.id
                    # Skip builtins and common imports
                    if (var_name not in dir(builtins) and var_name not in ('self', 'cls', 'super')
                            and var_name not in defined_vars):
                        # This is a potential undefined variable
                        code_issues.append({
                            "type": "UNDEFINED_VARIABLE",
                            "message": f"Potential undefined variable: '{var_name}'",
                            "node": node,
                            "is_critical": False
                        })
                
                # Track variable definitions
                elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                    var_name = node.id
                    if var_name not in defined_vars:
                        defined_vars[var_name] = []
                    defined_vars[var_name].append(node)
                    
                # Check for common critical issues
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    func_name = node.func.id
                    
                    # Check for dangerous functions
                    if func_name in ('eval', 'exec'):
                        code_issues.append({
                            "type": "DANGEROUS_FUNCTION",
                            "message": f"Potential security risk: usage of '{func_name}' function",
                            "node": node,
                            "is_critical": True
                        })
                
                # Check for unused imports (simplified)
                elif isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom):
                    # This is just a simple check - a full implementation would track usage
                    if isinstance(node, ast.Import):
                        for name in node.names:
                            imported_name = name.asname or name.name
                            # Add to defined vars to track usage
                            if imported_name not in defined_vars:
                                defined_vars[imported_name] = []
                            defined_vars[imported_name].append(node)
                    
            # Format code issues
            critical_issues = [issue for issue in code_issues if issue["is_critical"]]
            warning_issues = [issue for issue in code_issues if not issue["is_critical"]]
            
            if critical_issues:
                error_msg = "CRITICAL CODE QUALITY ISSUES:\n\n"
                for i, issue in enumerate(critical_issues, 1):
                    lineno = getattr(issue["node"], "lineno", "unknown")
                    col_offset = getattr(issue["node"], "col_offset", "unknown")
                    error_msg += f"{i}. {issue['type']}: {issue['message']} at line {lineno}, col {col_offset}\n"
                return False, error_msg
                
            # Non-critical issues are just warnings
            if warning_issues:
                warning_msg = "CODE QUALITY WARNINGS (not preventing execution):\n\n"
                for i, issue in enumerate(warning_issues, 1):
                    lineno = getattr(issue["node"], "lineno", "unknown")
                    warning_msg += f"{i}. {issue['message']} at line {lineno}\n"
                compatibility_issues.append({"message": warning_msg, "is_critical": False})
                
        except Exception as e:
            # Non-critical - static analysis failed but syntax is still valid
            compatibility_issues.append({
                "message": f"Code quality analysis error: {str(e)}",
                "is_critical": False
            })
            
        # If we have non-critical issues, return a warning, otherwise return success
        if compatibility_issues:
            warnings_text = "\n\n".join(issue["message"] for issue in compatibility_issues)
            return True, f"VALID SYNTAX WITH WARNINGS:\n\n{warnings_text}"
            
        return True, ""
            
    def _calculate_similarity(self, str1: str, str2: str) -> float:
        """Calculate similarity between two strings using Levenshtein distance."""
        if not str1 or not str2:
            return 0.0
            
        if str1 == str2:
            return 1.0
            
        len1: int = len(str1)
        len2: int = len(str2)
        
        matrix: list[list[int]] = [[0 for _ in range(len2 + 1)] for _ in range(len1 + 1)]
        
        for i in range(len1 + 1):
            matrix[i][0] = i
        for j in range(len2 + 1):
            matrix[0][j] = j
            
        for i in range(1, len1 + 1):
            for j in range(1, len2 + 1):
                cost: int = 0 if str1[i-1] == str2[j-1] else 1
                matrix[i][j] = min(
                    matrix[i-1][j] + 1,      # deletion
                    matrix[i][j-1] + 1,      # insertion
                    matrix[i-1][j-1] + cost  # substitution
                )
                
        distance: int = matrix[len1][len2]
        max_len: int = max(len1, len2)
        
        return 1.0 - (distance / max_len)
    
    def _find_similar_targets(self, content: str, target: str) -> list[tuple[str, float]]:
        """Find similar targets in the content using fuzzy matching."""
        import re
        
        pattern: re.Pattern = re.compile(r'(class|def)\s+(\w+)')
        matches: list[tuple[str, str]] = pattern.findall(content)
        
        targets: list[str] = []
        for match_type, name in matches:
            if match_type == 'class':
                targets.append(name)
                
                class_pattern: re.Pattern = re.compile(r'class\s+' + name + r'[^\n]*?:.*?(?=\n\S|$)', re.DOTALL)
                class_match = class_pattern.search(content)
                if class_match:
                    class_content: str = class_match.group(0)
                    method_pattern: re.Pattern = re.compile(r'def\s+(\w+)\s*\(')
                    method_matches: list[str] = method_pattern.findall(class_content)
                    
                    for method in method_matches:
                        targets.append(f"{name}.{method}")
            else:
                targets.append(name)
        
        similarities: list[tuple[str, float]] = []
        for t in targets:
            similarity: float = self._calculate_similarity(target, t)
            if similarity > 0.5:  # Threshold
                similarities.append((t, similarity))
                
        return sorted(similarities, key=lambda x: x[1], reverse=True)

    def _check_method_signature(self, original: str, replacement: str) -> list[str]:
        """Check method signature compatibility."""
        warnings: list[str] = []
        
        import re
        orig_sig = re.search(r'def\s+(\w+)\s*\((.*?)\)', original)
        new_sig = re.search(r'def\s+(\w+)\s*\((.*?)\)', replacement)
        
        if orig_sig and new_sig:
            orig_name: str = orig_sig.group(1)
            new_name: str = new_sig.group(1)
            
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
            
            for param in orig_params:
                if param not in new_params and param not in ['self', 'cls']:
                    warnings.append(f"Parameter '{param}' removed - this may break code that calls this method")
            
            for i, param in enumerate(new_params):
                if param not in orig_params:
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
                          auto_checkpoint: bool = False, dry_run: bool = False,
                          batch_mode: bool = False, process_imports: bool = True) -> dict[str, Any]:
        """Advanced text replacement using hierarchical selection."""
        # Check if file exists
        if not file_path.exists():
            raise ValueError(f"File not found: {file_path}")
            
        # Detect file encoding and line endings
        try:
            import chardet
            with open(file_path, 'rb') as f:
                sample: bytes = f.read(4096)
                encoding_result: dict[str, Any] = chardet.detect(sample)
                encoding: str = encoding_result['encoding'] or 'utf-8'
                
                # Check line endings
                crlf_count: int = sample.count(b'\r\n')
                lf_count: int = sample.count(b'\n') - crlf_count
                line_ending: str = '\r\n' if crlf_count > lf_count else '\n'
        except (ImportError, Exception):
            encoding = 'utf-8'
            line_ending = '\n'
        
        # Normalize replacement line endings to match the file
        if '\n' in replace_with and line_ending != '\n':
            replace_with = replace_with.replace('\n', line_ending)
            
        # Get original content
        content: str = await self._read_file_content(file_path)
        
        # Track changes and warnings
        result_data: dict[str, Any] = {
            "success": False,
            "message": "",
            "diff_output": "",
            "warnings": [],
            "errors": [],
            "modified_files": [str(file_path)],
            "encoding": encoding,
            "line_ending": line_ending,
            "original_content": content
        }
        
        # Process advanced highlight options
        if isinstance(highlight, dict):
            # Standardized approach using "target" key
            if "target" in highlight:
                target = highlight["target"]
                
                # Handle list of targets (multi-target replacement)
                if isinstance(target, list):
                    return await self._multi_target_replace(
                        file_path, target, replace_with, encoding,
                        checkpoint, auto_checkpoint, dry_run, result_data
                    )
                
                # Single target with related files
                if "related_files" in highlight:
                    try:
                        multifile_result: dict[str, Any] = await self._multi_file_replace(
                            file_path, target, highlight["related_files"], replace_with,
                            checkpoint, auto_checkpoint, dry_run, result_data
                        )
                        return multifile_result
                    except Exception as e:
                        result_data["errors"].append(str(e))
                        result_data["message"] = f"ERROR: Multi-file replacement failed: {e}"
                        return result_data
                
                # Default: treat as simple target
                highlight = target
                
            # Legacy support for old patterns (to be deprecated)
            elif "pattern" in highlight:
                try:
                    regex_result: dict[str, Any] = await self._regex_based_replace(
                        file_path, highlight["pattern"], replace_with, encoding, 
                        checkpoint, auto_checkpoint, dry_run, result_data
                    )
                    return regex_result
                except Exception as e:
                    result_data["errors"].append(str(e))
                    result_data["message"] = f"ERROR: Regex-based targeting failed: {e}"
                    return result_data
            
            elif "line_range" in highlight:
                try:
                    line_range_result: dict[str, Any] = await self._line_based_replace(
                        file_path, highlight["line_range"], replace_with, encoding,
                        checkpoint, auto_checkpoint, dry_run, result_data
                    )
                    return line_range_result
                except Exception as e:
                    result_data["errors"].append(str(e))
                    result_data["message"] = f"ERROR: Line-based targeting failed: {e}"
                    return result_data
            
            elif "targets" in highlight or "multi_targets" in highlight:
                targets: list[str] = highlight.get("targets", highlight.get("multi_targets", []))
                try:
                    multi_result: dict[str, Any] = await self._multi_target_replace(
                        file_path, targets, replace_with, encoding,
                        checkpoint, auto_checkpoint, dry_run, result_data
                    )
                    return multi_result
                except Exception as e:
                    result_data["errors"].append(str(e))
                    result_data["message"] = f"ERROR: Multi-target replacement failed: {e}"
                    return result_data
            
        # Standard validation for string-based highlight
        if isinstance(highlight, str):
            # Common mistake: including class/def keywords
            if highlight.startswith("class ") or highlight.startswith("def "):
                clean_highlight: str = highlight.split()[1].rstrip(':').rstrip('()')
                result_data["errors"].append(
                    f"HIGHLIGHT FORMAT ERROR: Do not include 'class' or 'def' keywords in highlight parameter."
                )
                result_data["message"] = (
                    f"FORMAT ERROR: Detected 'class' or 'def' prefix in highlight.\n"
                    f"INCORRECT: '{highlight}'\n"
                    f"CORRECT: '{clean_highlight}'"
                )
                
                # Auto-recovery attempt
                auto_fix_result: dict[str, Any] = await self._try_replace_with_clean_highlight(
                    file_path, clean_highlight, replace_with, encoding, checkpoint,
                    auto_checkpoint, dry_run, result_data
                )
                if auto_fix_result["success"]:
                    auto_fix_result["message"] = (
                        f"AUTO-FIXED: Removed 'class'/'def' prefix from highlight parameter.\n"
                        f"Used '{clean_highlight}' instead of '{highlight}'.\n" +
                        auto_fix_result["message"]
                    )
                    return auto_fix_result
                    
                return result_data
            
            # Common mistake: including parentheses or colons  
            if "(" in highlight or ":" in highlight:
                clean_highlight: str = highlight.split("(")[0].rstrip(":")
                result_data["errors"].append(
                    f"HIGHLIGHT FORMAT ERROR: Do not include parentheses or colons in highlight parameter."
                )
                result_data["message"] = (
                    f"FORMAT ERROR: Detected parentheses or colons in highlight.\n"
                    f"INCORRECT: '{highlight}'\n"
                    f"CORRECT: '{clean_highlight}'"
                )
                
                # Auto-recovery attempt
                auto_fix_result: dict[str, Any] = await self._try_replace_with_clean_highlight(
                    file_path, clean_highlight, replace_with, encoding, checkpoint,
                    auto_checkpoint, dry_run, result_data
                )
                if auto_fix_result["success"]:
                    auto_fix_result["message"] = (
                        f"AUTO-FIXED: Removed parentheses/colons from highlight parameter.\n"
                        f"Used '{clean_highlight}' instead of '{highlight}'.\n" +
                        auto_fix_result["message"]
                    )
                    return auto_fix_result
                    
                return result_data
        
        # Check for triple quotes in replacement text
        if not (replace_with.startswith('"""') or replace_with.startswith("'''")) and '\n' in replace_with:
            result_data["warnings"].append(
                "Multi-line replacement text should use triple quotes to preserve indentation."
            )
            
        # Validate replacement content for common definition errors
        if isinstance(highlight, str) and "." in highlight and '\n' in replace_with:
            # This is a method replacement - should start with def/async def
            method_name: str = highlight.split(".")[-1]
            first_line: str = replace_with.strip().split('\n')[0].strip()
            
            if not (first_line.startswith("def ") or first_line.startswith("async def ")):
                result_data["errors"].append(
                    f"When replacing method '{method_name}', the replacement text must start with 'def {method_name}' or 'async def {method_name}'."
                )
                result_data["message"] = (
                    f"ERROR: Method replacement must start with method definition.\n"
                    f"When replacing '{method_name}', start with 'def {method_name}' or 'async def {method_name}'."
                )
                return result_data
                
            if method_name not in first_line:
                result_data["errors"].append(
                    f"Method name mismatch. Replacing '{method_name}' but replacement defines a different method name in: '{first_line}'."
                )
                result_data["message"] = (
                    f"ERROR: Method name mismatch.\n"
                    f"Replacing '{method_name}' but found different name in: '{first_line}'."
                )
                return result_data
        
        # Start transaction
        transaction_id: str = await self.transaction_manager.begin()
        
        try:
            # Acquire lock to prevent concurrent modifications
            await self.transaction_manager.acquire_file_lock(transaction_id, file_path)
            
            # Create checkpoint if requested
            if (checkpoint or auto_checkpoint) and not dry_run:
                checkpoint_name: str = checkpoint or f"text_replace_{file_path.name}_{transaction_id[:8]}"
                try:
                    with open(file_path, 'rb') as f:
                        file_bytes: bytes = f.read()
                    await self.transaction_manager.create_checkpoint(transaction_id, file_path, checkpoint_name)
                except Exception as e:
                    result_data["warnings"].append(f"Failed to create checkpoint: {e}")
            
            # Get the appropriate parser based on file extension
            try:
                parser = get_parser_for_file(file_path)
            except ValueError as e:
                # Fallback to basic replacements for unsupported file types
                if "Unsupported file type" in str(e):
                    fallback_result: dict[str, Any] = await self._basic_replacement_fallback(
                        file_path, highlight, replace_with, encoding, 
                        transaction_id, dry_run, result_data
                    )
                    return fallback_result
                raise
            
            # Parse the highlight pattern to find the target
            try:
                result = parser.find_target(content, highlight)
                
                # Set line ending in result for preservation
                result.line_ending = line_ending
                
                # Get original block for method signature compatibility check
                original_block: str = content[result.start_pos:result.end_pos]
            except ValueError as e:
                # Attempt fuzzy recovery
                recovery_result: dict[str, Any] = await self._try_fuzzy_recovery(
                    file_path, highlight, replace_with, encoding, transaction_id,
                    dry_run, result_data, content
                )
                
                if recovery_result["success"]:
                    if dry_run:
                        recovery_result["message"] = (
                            f"FUZZY RECOVERY: Found similar target.\n"
                            f"Use highlight='{recovery_result['target']}' for exact match.\n\n" +
                            recovery_result["message"]
                        )
                        recovery_result["warnings"].append("Used fuzzy matching for target")
                    return recovery_result
                
                # Add similarity suggestions
                similar_targets: list[tuple[str, float]] = self.find_similar_targets(
                    file_path, highlight if isinstance(highlight, str) else "", content
                )
                
                suggestions: str = ""
                if similar_targets:
                    suggestions = "Similar targets found:\n"
                    for target, score in similar_targets[:5]:
                        suggestions += f"- '{target}' (similarity: {score:.0%})\n"
                    
                result_data["similar_targets"] = similar_targets
                result_data["message"] = f"ERROR: Target not found. {suggestions}\n{str(e)}"
                await self.transaction_manager.rollback(transaction_id)
                return result_data
            
            # Check for method signature compatibility if this is a method replacement
            if isinstance(highlight, str) and "." in highlight and file_path.suffix.lower() == '.py':
                compatibility_warnings: list[str] = self._check_method_signature(original_block, replace_with)
                if compatibility_warnings:
                    for warning in compatibility_warnings:
                        result_data["warnings"].append(warning)
            
            # Process imports if requested (for Python files)
            if process_imports and file_path.suffix.lower() == '.py':
                replace_with = await self._process_imports(
                    content, original_block, replace_with, result_data
                )
            
            # Perform advanced type compatibility checks for Python files
            if file_path.suffix.lower() == '.py':
                type_issues = await self._check_type_compatibility(original_block, replace_with)
                
                # Filter critical vs. warning issues
                critical_type_issues = [issue for issue in type_issues if issue.get("is_critical", False)]
                warning_type_issues = [issue for issue in type_issues if not issue.get("is_critical", False)]
                
                # If we have critical type issues, abort the replacement
                if critical_type_issues:
                    error_msg: str = "CRITICAL TYPE COMPATIBILITY ERRORS:\n\n"
                    for i, issue in enumerate(critical_type_issues, 1):
                        error_msg += f"{i}. {issue['type']}: {issue['message']}\n"
                    
                    error_msg += "\nThese type changes would break compatibility with existing code.\n"
                    error_msg += "No changes have been applied to your code."
                    
                    result_data["errors"].append(error_msg)
                    result_data["message"] = error_msg
                    result_data["type_compatibility_errors"] = critical_type_issues
                    
                    await self.transaction_manager.rollback(transaction_id)
                    return result_data
                
                # Add warnings for non-critical issues
                if warning_type_issues:
                    warning_msg: str = "TYPE COMPATIBILITY WARNINGS:\n\n"
                    for i, issue in enumerate(warning_type_issues, 1):
                        warning_msg += f"{i}. {issue['message']}\n"
                    
                    result_data["warnings"].append(warning_msg)
                
            # Pre-validate replacement text syntax if it's a Python file
            if file_path.suffix.lower() == '.py':
                is_valid: bool
                validation_msg: str
                is_valid, validation_msg = self._validate_python_syntax(replace_with)
                
                if not is_valid:
                    # Critical syntax error - halt immediately
                    result_data["errors"].append(validation_msg)
                    result_data["message"] = (
                        "CRITICAL SYNTAX ERROR DETECTED\n\n"
                        f"{validation_msg}\n\n"
                        "The replacement code contains invalid Python syntax and would break your codebase.\n"
                        "No changes have been applied."
                    )
                    await self.transaction_manager.rollback(transaction_id)
                    return result_data
                elif validation_msg:
                    # Valid syntax but with warnings
                    result_data["warnings"].append(validation_msg)
                    
                    # Check if these are just warnings or include critical issues
                    if "CRITICAL" in validation_msg:
                        # Use a distinctive message for serious warnings
                        confirmation_msg = (
                            "⚠️ CODE VALIDATION WARNINGS DETECTED ⚠️\n\n"
                            f"{validation_msg}\n\n"
                            "These warnings do not prevent the code from executing, but may indicate potential issues.\n"
                            "Please review them carefully before proceeding.\n\n"
                            "Would you like to proceed with the replacement anyway? (Try with dry_run=True first to preview changes)"
                        )
                        result_data["requires_confirmation"] = True
                        result_data["confirmation_message"] = confirmation_msg
                        
                        # If this is not a dry run, we should proceed with caution
                        if not dry_run:
                            # For this implementation, we'll still proceed but with prominent warnings
                            # In a real interactive system, we might pause for confirmation
                            result_data["warnings"].append(
                                "Proceeding with replacement despite validation warnings. Proceed with caution!"
                            )
                    # If there are only minor warnings, we just include them but proceed normally

            # CRITICAL: Enhanced indentation validation with strict rules
            if len(replace_with.splitlines()) > 1:
                # Track detailed indentation issues
                indentation_errors: list[dict[str, Any]] = []
                
                # Extract first line indentation style for baseline
                first_content_line_idx: int = -1
                for idx, line in enumerate(replace_with.splitlines()):
                    if line.strip():
                        first_content_line_idx = idx
                        break
                        
                if first_content_line_idx == -1:
                    # No content lines found - unusual but not an error
                    pass
                else:
                    first_content_line: str = replace_with.splitlines()[first_content_line_idx]
                    first_leading_whitespace: str = first_content_line[:len(first_content_line) - len(first_content_line.lstrip())]
                    base_indent_char: str = '\t' if '\t' in first_leading_whitespace else ' '
                    base_indent_size: int = len(first_leading_whitespace)
                    
                    # Calculate standard indentation unit (typically 2, 4, or 8 spaces)
                    indent_unit: int = 4  # Default
                    if base_indent_char == ' ' and base_indent_size > 0:
                        for line in replace_with.splitlines()[first_content_line_idx+1:]:
                            if line.strip():
                                curr_whitespace: str = line[:len(line) - len(line.lstrip())]
                                if len(curr_whitespace) > base_indent_size:
                                    indent_unit = len(curr_whitespace) - base_indent_size
                                    break
                    
                    # Validate all non-empty lines with extremely strict rules
                    for idx, line in enumerate(replace_with.splitlines()):
                        if not line.strip():  # Skip empty lines
                            continue
                            
                        # Extract the leading whitespace
                        leading_whitespace: str = line[:len(line) - len(line.lstrip())]
                        whitespace_len: int = len(leading_whitespace)
                        
                        # CRITICAL ERROR: Mixed tabs and spaces
                        if ' ' in leading_whitespace and '\t' in leading_whitespace:
                            error_info = {
                                "line_number": idx + 1,
                                "line_content": line,
                                "error_type": "MIXED_INDENTATION",
                                "message": f"Line {idx + 1} contains both tabs AND spaces for indentation",
                                "critical": True,
                                "suggestion": "Choose either tabs OR spaces for indentation, never mix them"
                            }
                            indentation_errors.append(error_info)
                        
                        # CRITICAL ERROR: Inconsistent indentation character
                        if leading_whitespace and (('\t' in leading_whitespace and base_indent_char == ' ') or 
                                                (' ' in leading_whitespace and base_indent_char == '\t')):
                            error_info = {
                                "line_number": idx + 1,
                                "line_content": line,
                                "error_type": "INCONSISTENT_CHAR",
                                "message": f"Line {idx + 1} uses indentation that doesn't match the rest of the code",
                                "critical": True,
                                "suggestion": f"Use consistent {base_indent_char} throughout the entire code block"
                            }
                            indentation_errors.append(error_info)
                        
                        # CRITICAL ERROR: Indentation not a multiple of the standard unit
                        if base_indent_char == ' ' and whitespace_len % indent_unit != 0 and whitespace_len > 0:
                            error_info = {
                                "line_number": idx + 1,
                                "line_content": line,
                                "error_type": "INVALID_INDENT_SIZE",
                                "message": f"Line {idx + 1} has {whitespace_len} spaces indentation which is not a multiple of {indent_unit}",
                                "critical": True,
                                "suggestion": f"Use indentation that's a multiple of {indent_unit} spaces"
                            }
                            indentation_errors.append(error_info)
                
                # If any critical indentation errors were found, halt execution immediately
                if indentation_errors:
                    # Format a detailed error message with line numbers and code snippets
                    error_msg: str = "CRITICAL INDENTATION ERRORS DETECTED:\n\n"
                    
                    for i, error in enumerate(indentation_errors, 1):
                        error_msg += f"ERROR #{i}: {error['error_type']} - {error['message']}\n"
                        
                        # Create a visual representation of the indentation problem
                        line_content = error['line_content']
                        leading_whitespace = line_content[:len(line_content) - len(line_content.lstrip())]
                        
                        # Add a visual marker for the indentation character issues
                        whitespace_marker = ""
                        for char in leading_whitespace:
                            if char == ' ':
                                whitespace_marker += "·"  # Visualize spaces with middle dots
                            elif char == '\t':
                                whitespace_marker += "→"  # Visualize tabs with right arrows
                        
                        # Show the code with highlighted indentation markers
                        error_msg += f"    {line_content}\n"
                        error_msg += f"    {whitespace_marker}{'^' * len(line_content.lstrip())}\n"
                        error_msg += f"Suggestion: {error['suggestion']}\n\n"
                    
                    error_msg += "\nPython is extremely sensitive to proper indentation. Fix these errors before proceeding."
                    error_msg += "\nNo changes have been applied to your code."
                    
                    # Add the error message to result_data
                    result_data["errors"].append(error_msg)
                    result_data["message"] = error_msg
                    result_data["critical_indentation_errors"] = indentation_errors
                    
                    # Rollback any transaction and return with failure
                    await self.transaction_manager.rollback(transaction_id)
                    return result_data
            
            # Apply the replacement while preserving formatting
            new_content: str = parser.apply_replacement(content, result, replace_with)
            
            # Generate diff for preview or dry run
            import difflib
            diff: list[str] = list(difflib.unified_diff(
                content.splitlines(),
                new_content.splitlines(),
                fromfile=f"{file_path} (original)",
                tofile=f"{file_path} (modified)",
                lineterm="",
                n=3  # Context lines
            ))
            
            if diff:
                diff_text: str = "\n".join(diff)
                result_data["diff_output"] = diff_text
            else:
                result_data["diff_output"] = "No changes detected"
                result_data["message"] = "No changes needed - content is identical"
                await self.transaction_manager.rollback(transaction_id)
                return result_data
            
            # Check if this is a dry run
            if dry_run:
                await self.transaction_manager.rollback(transaction_id)
                result_data["message"] = "DRY RUN: Changes preview generated"
                return result_data
            
            # Validate the resulting content for syntax errors (for Python files)
            if file_path.suffix.lower() == '.py':
                is_valid: bool
                error_msg: str
                is_valid, error_msg = self._validate_python_syntax(new_content)
                if not is_valid:
                    result_data["errors"].append(error_msg)
                    result_data["message"] = f"SYNTAX ERROR: {error_msg}\nChanges NOT applied."
                    await self.transaction_manager.rollback(transaction_id)
                    return result_data
            
            # Write the modified content with original encoding
            await self.transaction_manager.write_to_temp(
                transaction_id, file_path, new_content.encode(encoding, errors='replace')
            )
            
            # Commit the transaction
            await self.transaction_manager.commit(transaction_id)
            
            # Update success info
            result_data["success"] = True
            result_data["new_content"] = new_content
            result_data["message"] = f"✓ Successfully replaced content in {file_path}"
            
            # Add warning count info if any
            if result_data["warnings"]:
                result_data["message"] += f" ({len(result_data['warnings'])} warnings)"
                
            return result_data
            
        except Exception as e:
            # Rollback on any error
            await self.transaction_manager.rollback(transaction_id)
            raise ValueError(f"Failed to replace text: {str(e)}")

    async def find_similar_targets(self, file_path: Path, target: str, content: str | None = None) -> list[tuple[str, float]]:
        """Find similar targets to the requested target.
        
        This is used for fuzzy matching and error recovery.
        """
        if not content:
            content = await self._read_file_content(file_path)
            
        import re
        
        pattern: re.Pattern = re.compile(r'(class|def)\s+(\w+)')
        matches: list[tuple[str, str]] = pattern.findall(content)
        
        targets: list[str] = []
        class_methods: dict[str, list[str]] = {}
        
        for match_type, name in matches:
            if match_type == 'class':
                targets.append(name)
                class_methods[name] = []
                
                # Find methods within the class
                class_pattern: re.Pattern = re.compile(
                    r'class\s+' + re.escape(name) + r'[^\n]*?:.*?(?=\n\S|$)', 
                    re.DOTALL
                )
                class_match: re.Match | None = class_pattern.search(content)
                if class_match:
                    class_content: str = class_match.group(0)
                    method_pattern: re.Pattern = re.compile(r'def\s+(\w+)\s*\(')
                    method_matches: list[str] = method_pattern.findall(class_content)
                    
                    for method in method_matches:
                        targets.append(f"{name}.{method}")
                        class_methods[name].append(method)
            elif match_type == 'def':
                # Only add top-level functions
                parent_pattern: re.Pattern = re.compile(
                    r'class\s+\w+[^\n]*?:.*?' + re.escape(f'def {name}') + r'.*?(?=\n\S|$)', 
                    re.DOTALL
                )
                parent_match: re.Match | None = parent_pattern.search(content)
                if not parent_match:
                    targets.append(name)
        
        # Calculate similarities
        similarities: list[tuple[str, float]] = []
        for t in targets:
            similarity: float = self._calculate_similarity(target, t)
            if similarity > 0.5:  # Threshold for suggestions
                similarities.append((t, similarity))
        
        # Sort by similarity score
        return sorted(similarities, key=lambda x: x[1], reverse=True)
    
    async def try_fuzzy_recovery(self, file_path: Path, highlight: str | dict, 
                                replace_with: str, auto_checkpoint: bool = False,
                                threshold: float = 0.8, dry_run: bool = False) -> dict[str, Any] | None:
        """Try to recover from a failed target search using fuzzy matching."""
        content: str = await self._read_file_content(file_path)
        
        # Convert dictionary highlight to string if possible
        target: str = highlight if isinstance(highlight, str) else highlight.get("target", "")
        if not target:
            return None
            
        # Find similar targets
        similar_targets: list[tuple[str, float]] = await self.find_similar_targets(file_path, target, content)
        
        # If we have a good match, try using it
        if similar_targets and similar_targets[0][1] >= threshold:
            best_match: str = similar_targets[0][0]
            
            # Create a modified highlight (preserve advanced options from dict)
            modified_highlight: str | dict = best_match
            if isinstance(highlight, dict):
                modified_highlight = highlight.copy()
                modified_highlight["target"] = best_match
            
            # Recursively attempt replacement with the modified highlight
            try:
                result: dict[str, Any] = await self.text_replace(
                    file_path, modified_highlight, replace_with, None, 
                    auto_checkpoint, dry_run=dry_run
                )
                if result["success"]:
                    result["target"] = best_match
                    result["similarity"] = similar_targets[0][1]
                    result["fuzzy_recovery"] = True
                    return result
            except Exception:
                pass
        
        return None
        
    async def _try_replace_with_clean_highlight(self, file_path: Path, clean_highlight: str,
                                              replace_with: str, encoding: str, checkpoint: str | None,
                                              auto_checkpoint: bool, dry_run: bool,
                                              result_data: dict[str, Any]) -> dict[str, Any]:
        """Try replacing content with cleaned highlight."""
        try:
            auto_result: dict[str, Any] = await self.text_replace(
                file_path, clean_highlight, replace_with, checkpoint,
                auto_checkpoint, dry_run
            )
            auto_result["auto_fixed"] = True
            auto_result["original_highlight"] = clean_highlight
            return auto_result
        except Exception as e:
            result_data["errors"].append(f"Auto-recovery failed: {e}")
            return result_data
            
    async def _basic_replacement_fallback(self, file_path: Path, highlight: str | dict,
                                        replace_with: str, encoding: str, transaction_id: str,
                                        dry_run: bool, result_data: dict[str, Any]) -> dict[str, Any]:
        """Basic replacement fallback for unsupported file types."""
        content: str = result_data["original_content"]
        
        # Extract text match pattern
        match_pattern: str = ""
        if isinstance(highlight, str):
            match_pattern = highlight
        elif isinstance(highlight, dict):
            match_pattern = highlight.get("target", highlight.get("pattern", ""))
        
        if not match_pattern:
            result_data["errors"].append("No valid target or pattern provided")
            result_data["message"] = "ERROR: No valid target or pattern specified"
            await self.transaction_manager.rollback(transaction_id)
            return result_data
            
        # Try to perform basic text replacement
        import re
        if re.search(match_pattern, content):
            new_content: str = re.sub(match_pattern, replace_with, content)
            
            # Generate diff
            import difflib
            diff: list[str] = list(difflib.unified_diff(
                content.splitlines(),
                new_content.splitlines(),
                fromfile=f"{file_path} (original)",
                tofile=f"{file_path} (modified)",
                lineterm="",
                n=3
            ))
            
            result_data["diff_output"] = "\n".join(diff)
            
            if dry_run:
                result_data["message"] = "DRY RUN: Basic text replacement preview generated"
                await self.transaction_manager.rollback(transaction_id)
                return result_data
                
            # Write changes
            await self.transaction_manager.write_to_temp(
                transaction_id, file_path, new_content.encode(encoding)
            )
            await self.transaction_manager.commit(transaction_id)
            
            result_data["success"] = True
            result_data["message"] = f"Basic text replacement completed for {file_path}"
            result_data["new_content"] = new_content
            result_data["warnings"].append("Used basic text replacement due to unsupported file type")
            
            return result_data
        else:
            result_data["errors"].append(f"Pattern '{match_pattern}' not found in file")
            result_data["message"] = f"ERROR: Pattern '{match_pattern}' not found in file"
            await self.transaction_manager.rollback(transaction_id)
            return result_data
            
    async def _regex_based_replace(self, file_path: Path, pattern: str, replace_with: str,
                                  encoding: str, checkpoint: str | None, auto_checkpoint: bool,
                                  dry_run: bool, result_data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Perform regex-based targeting and replacement."""
        if result_data is None:
            result_data = {
                "success": False,
                "message": "",
                "warnings": [],
                "errors": [],
                "modified_files": [str(file_path)]
            }
            
        content: str = await self._read_file_content(file_path)
        
        # Validate regex pattern
        try:
            import re
            regex: re.Pattern = re.compile(pattern, re.DOTALL)
        except re.error as e:
            result_data["errors"].append(f"Invalid regex pattern: {e}")
            result_data["message"] = f"ERROR: Invalid regex pattern: {e}"
            return result_data
            
        # Find matches
        matches: list[re.Match] = list(regex.finditer(content))
        if not matches:
            result_data["errors"].append(f"Regex pattern not found: {pattern}")
            result_data["message"] = f"ERROR: Regex pattern not found: {pattern}"
            return result_data
            
        # Start transaction
        transaction_id: str = await self.transaction_manager.begin()
        
        try:
            # Acquire lock
            await self.transaction_manager.acquire_file_lock(transaction_id, file_path)
            
            # Create checkpoint if needed
            if (checkpoint or auto_checkpoint) and not dry_run:
                checkpoint_name: str = checkpoint or f"regex_replace_{file_path.name}_{transaction_id[:8]}"
                try:
                    await self.transaction_manager.create_checkpoint(transaction_id, file_path, checkpoint_name)
                except Exception as e:
                    result_data["warnings"].append(f"Failed to create checkpoint: {e}")
            
            # Apply replacement to all matches (in reverse to preserve positions)
            new_content: str = content
            for match in reversed(matches):
                original_text: str = match.group(0)
                start_pos: int = match.start()
                end_pos: int = match.end()
                
                # Apply replacement with any replacement groups
                if '\\' in replace_with or '$' in replace_with:
                    replaced_text: str = regex.sub(replace_with, original_text)
                else:
                    replaced_text: str = replace_with
                    
                # Apply the replacement
                new_content = new_content[:start_pos] + replaced_text + new_content[end_pos:]
            
            # Generate diff
            import difflib
            diff: list[str] = list(difflib.unified_diff(
                content.splitlines(),
                new_content.splitlines(),
                fromfile=f"{file_path} (original)",
                tofile=f"{file_path} (modified)",
                lineterm="",
                n=3
            ))
            
            result_data["diff_output"] = "\n".join(diff) if diff else "No changes"
            result_data["match_count"] = len(matches)
            
            if not diff:
                result_data["message"] = "No changes needed - replacement produces identical content"
                await self.transaction_manager.rollback(transaction_id)
                return result_data
                
            # Check if this is dry run
            if dry_run:
                result_data["message"] = f"DRY RUN: Found {len(matches)} matches for pattern"
                await self.transaction_manager.rollback(transaction_id)
                return result_data
                
            # Write changes
            await self.transaction_manager.write_to_temp(
                transaction_id, file_path, new_content.encode(encoding)
            )
            await self.transaction_manager.commit(transaction_id)
            
            result_data["success"] = True
            result_data["new_content"] = new_content
            result_data["message"] = f"✓ Successfully replaced {len(matches)} regex matches in {file_path}"
            
            return result_data
            
        except Exception as e:
            await self.transaction_manager.rollback(transaction_id)
            result_data["errors"].append(str(e))
            result_data["message"] = f"ERROR: Regex replacement failed: {e}"
            return result_data
            
    async def _line_based_replace(self, file_path: Path, line_range: tuple[int, int] | list[int],
                                 replace_with: str, encoding: str, checkpoint: str | None,
                                 auto_checkpoint: bool, dry_run: bool,
                                 result_data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Replace content based on line numbers."""
        if result_data is None:
            result_data = {
                "success": False,
                "message": "",
                "warnings": [],
                "errors": [],
                "modified_files": [str(file_path)]
            }
            
        content: str = await self._read_file_content(file_path)
        lines: list[str] = content.splitlines(keepends=True)
        
        # Validate line range
        start_line: int = line_range[0]
        end_line: int = line_range[1]
        
        if start_line < 0 or start_line >= len(lines):
            result_data["errors"].append(f"Invalid start line: {start_line}")
            result_data["message"] = f"ERROR: Invalid start line {start_line} (file has {len(lines)} lines)"
            return result_data
            
        if end_line < start_line or end_line >= len(lines):
            result_data["errors"].append(f"Invalid end line: {end_line}")
            result_data["message"] = f"ERROR: Invalid end line {end_line} (file has {len(lines)} lines)"
            return result_data
            
        # Start transaction
        transaction_id: str = await self.transaction_manager.begin()
        
        try:
            # Acquire lock
            await self.transaction_manager.acquire_file_lock(transaction_id, file_path)
            
            # Create checkpoint if needed
            if (checkpoint or auto_checkpoint) and not dry_run:
                checkpoint_name: str = checkpoint or f"line_replace_{file_path.name}_{transaction_id[:8]}"
                try:
                    await self.transaction_manager.create_checkpoint(transaction_id, file_path, checkpoint_name)
                except Exception as e:
                    result_data["warnings"].append(f"Failed to create checkpoint: {e}")
            
            # Extract original content
            original_content: str = "".join(lines[start_line:end_line+1])
            
            # Detect indentation in original content
            indentation: str = ""
            for line in lines[start_line:end_line+1]:
                if line.strip():
                    indentation = line[:len(line) - len(line.lstrip())]
                    break
            
            # Apply indentation to replacement
            replacement_lines: list[str] = replace_with.splitlines(keepends=True)
            if len(replacement_lines) > 0 and indentation:
                for i in range(len(replacement_lines)):
                    if replacement_lines[i].strip():
                        # Don't indent first line if it's at same level
                        if i == 0 and replacement_lines[i].startswith(indentation):
                            continue
                        # Indent other lines
                        replacement_lines[i] = indentation + replacement_lines[i].lstrip()
            
            # Create new content
            new_lines: list[str] = lines[:start_line] + replacement_lines + lines[end_line+1:]
            new_content: str = "".join(new_lines)
            
            # Generate diff
            import difflib
            diff: list[str] = list(difflib.unified_diff(
                content.splitlines(),
                new_content.splitlines(),
                fromfile=f"{file_path} (original)",
                tofile=f"{file_path} (modified)",
                lineterm="",
                n=3
            ))
            
            result_data["diff_output"] = "\n".join(diff) if diff else "No changes"
            
            if not diff:
                result_data["message"] = "No changes needed - replacement produces identical content"
                await self.transaction_manager.rollback(transaction_id)
                return result_data
                
            # Check if this is dry run
            if dry_run:
                result_data["message"] = f"DRY RUN: Replace lines {start_line}-{end_line}"
                await self.transaction_manager.rollback(transaction_id)
                return result_data
                
            # Write changes
            await self.transaction_manager.write_to_temp(
                transaction_id, file_path, new_content.encode(encoding)
            )
            await self.transaction_manager.commit(transaction_id)
            
            result_data["success"] = True
            result_data["new_content"] = new_content
            result_data["message"] = f"✓ Successfully replaced lines {start_line}-{end_line} in {file_path}"
            
            return result_data
            
        except Exception as e:
            await self.transaction_manager.rollback(transaction_id)
            result_data["errors"].append(str(e))
            result_data["message"] = f"ERROR: Line-based replacement failed: {e}"
            return result_data
            
    async def _multi_target_replace(self, file_path: Path, targets: list[str], replace_with: str | dict[str, str],
                                   encoding: str, checkpoint: str | None, auto_checkpoint: bool,
                                   dry_run: bool, result_data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Replace multiple targets with standardized approach.
        
        Handles two cases:
        1. Single replacement for all targets: replace_with is a string
        2. Target-specific replacements: replace_with is a dictionary {target: replacement}
        """
        if result_data is None:
            result_data = {
                "success": False,
                "message": "",
                "warnings": [],
                "errors": [],
                "modified_files": [str(file_path)],
                "targets": targets
            }
            
        # Start transaction
        transaction_id: str = await self.transaction_manager.begin()
        
        try:
            # Acquire lock
            await self.transaction_manager.acquire_file_lock(transaction_id, file_path)
            
            content: str = await self._read_file_content(file_path)
            
            # Create checkpoint if needed
            if (checkpoint or auto_checkpoint) and not dry_run:
                checkpoint_name: str = checkpoint or f"multi_replace_{file_path.name}_{transaction_id[:8]}"
                try:
                    await self.transaction_manager.create_checkpoint(transaction_id, file_path, checkpoint_name)
                except Exception as e:
                    result_data["warnings"].append(f"Failed to create checkpoint: {e}")
            
            # Try to find each target
            successful_targets: list[str] = []
            failed_targets: list[str] = []
            error_messages: list[str] = []
            parser = get_parser_for_file(file_path)
            new_content: str = content
            
            # Process targets in order
            for target in targets:
                try:
                    # Find the target in the current version of the content
                    result = parser.find_target(new_content, target)
                    
                    # Get original block
                    original_block: str = new_content[result.start_pos:result.end_pos]
                    
                    # Get replacement for this target
                    if isinstance(replace_with, dict):
                        if target not in replace_with:
                            result_data["warnings"].append(f"No replacement provided for '{target}', skipping")
                            continue
                        target_replacement: str = replace_with[target]
                    else:
                        # Use the same replacement for all targets
                        target_replacement: str = replace_with
                    
                    # Apply replacement
                    target_result: str = parser.apply_replacement(new_content, result, target_replacement)
                    
                    # Update new_content for next target
                    new_content = target_result
                    successful_targets.append(target)
                except Exception as e:
                    failed_targets.append(target)
                    error_messages.append(f"Failed to replace '{target}': {str(e)}")
            
            # Generate diff
            import difflib
            diff: list[str] = list(difflib.unified_diff(
                content.splitlines(),
                new_content.splitlines(),
                fromfile=f"{file_path} (original)",
                tofile=f"{file_path} (modified)",
                lineterm="",
                n=3
            ))
            
            result_data["diff_output"] = "\n".join(diff) if diff else "No changes"
            result_data["successful_targets"] = successful_targets
            result_data["failed_targets"] = failed_targets
            
            if not successful_targets:
                result_data["errors"].extend(error_messages)
                result_data["message"] = f"ERROR: No targets were successfully replaced"
                await self.transaction_manager.rollback(transaction_id)
                return result_data
                
            if not diff:
                result_data["message"] = "No changes needed - replacement produces identical content"
                await self.transaction_manager.rollback(transaction_id)
                return result_data
                
            # Check if this is dry run
            if dry_run:
                result_data["message"] = (
                    f"DRY RUN: {len(successful_targets)} of {len(targets)} targets replaced successfully"
                )
                if failed_targets:
                    result_data["message"] += f" ({len(failed_targets)} failed)"
                await self.transaction_manager.rollback(transaction_id)
                return result_data
                
            # Write changes
            await self.transaction_manager.write_to_temp(
                transaction_id, file_path, new_content.encode(encoding)
            )
            await self.transaction_manager.commit(transaction_id)
            
            result_data["success"] = True
            result_data["new_content"] = new_content
            result_data["message"] = (
                f"✓ Successfully replaced {len(successful_targets)} of {len(targets)} targets in {file_path}"
            )
            
            if failed_targets:
                for msg in error_messages:
                    result_data["warnings"].append(msg)
                result_data["message"] += f" ({len(failed_targets)} failed)"
            
            return result_data
            
        except Exception as e:
            await self.transaction_manager.rollback(transaction_id)
            result_data["errors"].append(str(e))
            result_data["message"] = f"ERROR: Multi-target replacement failed: {e}"
            return result_data
            
    # The _occurrence_based_replace method was removed as it was unnecessary.
    # For targeting specific occurrences of a class or method, use the standard
    # qualified name approach: "Class1.method" instead of occurrence-based targeting.
            
    async def _multi_file_replace(self, file_path: Path, primary_target: str, related_files: list[str],
                                 replace_with: str, checkpoint: str | None, auto_checkpoint: bool,
                                 dry_run: bool, result_data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Replace content across multiple related files."""
        if result_data is None:
            result_data = {
                "success": False,
                "message": "",
                "warnings": [],
                "errors": [],
                "modified_files": [str(file_path)],
                "related_files": related_files
            }
            
        # Process the primary file first
        primary_result: dict[str, Any] = await self.text_replace(
            file_path, primary_target, replace_with, checkpoint,
            auto_checkpoint, dry_run
        )
        
        result_data["primary_result"] = primary_result
        
        if not primary_result["success"] and not dry_run:
            result_data["errors"].append(f"Failed to replace primary target in {file_path}")
            result_data["message"] = f"ERROR: Failed to replace primary target in {file_path}"
            return result_data
            
        # Process related files
        related_results: dict[str, dict[str, Any]] = {}
        successful_files: int = 1 if primary_result["success"] or dry_run else 0  # Count primary file
        
        for related_file in related_files:
            related_path: Path = Path(related_file)
            if not related_path.exists():
                result_data["warnings"].append(f"Related file not found: {related_file}")
                related_results[related_file] = {"success": False, "message": "File not found"}
                continue
                
            try:
                # Use the same target in related files
                file_result: dict[str, Any] = await self.text_replace(
                    related_path, primary_target, replace_with, checkpoint,
                    auto_checkpoint, dry_run
                )
                
                related_results[related_file] = file_result
                
                if file_result["success"] or dry_run:
                    successful_files += 1
                    result_data["modified_files"].append(str(related_path))
            except Exception as e:
                result_data["warnings"].append(f"Failed to process {related_file}: {e}")
                related_results[related_file] = {"success": False, "message": str(e)}
        
        result_data["related_results"] = related_results
        
        # Final status message
        total_files: int = len(related_files) + 1  # +1 for primary file
        
        if dry_run:
            result_data["success"] = True
            result_data["message"] = (
                f"DRY RUN: Replacement preview for {total_files} files"
            )
        else:
            result_data["success"] = successful_files > 0
            result_data["message"] = (
                f"✓ Successfully replaced target in {successful_files} of {total_files} files"
            )
            
        return result_data
        
    async def _check_type_compatibility(self, original_code: str, replacement_code: str) -> list[dict[str, Any]]:
        """
        Analyze type compatibility between original and replacement code.
        
        Performs static analysis to detect potential type-related issues when replacing code:
        - Method signature changes (parameter types, return types)
        - Type annotation changes that could break compatibility
        - Missing/changed annotations that could affect static type checking
        
        Args:
            original_code: The original code block being replaced
            replacement_code: The new code block
            
        Returns:
            List of type compatibility issues found
        """
        type_issues: list[dict[str, Any]] = []
        
        try:
            import ast
            import re
            
            # Parse both code blocks
            try:
                original_ast = ast.parse(original_code)
                replacement_ast = ast.parse(replacement_code)
            except SyntaxError:
                # If syntax parsing fails, we'll already catch this in _validate_python_syntax
                return []
                
            # Extract function definitions from both
            original_funcs: dict[str, dict[str, Any]] = {}
            replacement_funcs: dict[str, dict[str, Any]] = {}
            
            # Helper function to extract type annotations from a function
            def extract_function_types(node: ast.FunctionDef) -> dict[str, Any]:
                function_types = {
                    "name": node.name,
                    "return_type": None,
                    "parameters": {},
                    "has_annotations": False
                }
                
                # Extract return type annotation
                if hasattr(node, 'returns') and node.returns:
                    function_types["has_annotations"] = True
                    if isinstance(node.returns, ast.Name):
                        function_types["return_type"] = node.returns.id
                    elif isinstance(node.returns, ast.Constant):
                        function_types["return_type"] = str(node.returns.value)
                    elif isinstance(node.returns, ast.Subscript):
                        # Handle complex types like List[int]
                        function_types["return_type"] = ast.unparse(node.returns) if hasattr(ast, 'unparse') else "complex_type"
                    else:
                        # For other types of return annotations
                        function_types["return_type"] = "complex_type"
                
                # Extract parameter types
                for arg in node.args.args:
                    if hasattr(arg, 'annotation') and arg.annotation:
                        function_types["has_annotations"] = True
                        if isinstance(arg.annotation, ast.Name):
                            function_types["parameters"][arg.arg] = arg.annotation.id
                        elif isinstance(arg.annotation, ast.Constant):
                            function_types["parameters"][arg.arg] = str(arg.annotation.value)
                        elif isinstance(arg.annotation, ast.Subscript):
                            # Handle complex types
                            function_types["parameters"][arg.arg] = ast.unparse(arg.annotation) if hasattr(ast, 'unparse') else "complex_type"
                        else:
                            function_types["parameters"][arg.arg] = "complex_type"
                    else:
                        function_types["parameters"][arg.arg] = None
                        
                return function_types
            
            # Extract functions from original code
            for node in ast.walk(original_ast):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    original_funcs[node.name] = extract_function_types(node)
            
            # Extract functions from replacement code
            for node in ast.walk(replacement_ast):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    replacement_funcs[node.name] = extract_function_types(node)
            
            # Compare functions for type compatibility
            for func_name, orig_func in original_funcs.items():
                if func_name in replacement_funcs:
                    new_func = replacement_funcs[func_name]
                    
                    # Check return type compatibility
                    if orig_func["return_type"] != new_func["return_type"]:
                        if orig_func["return_type"] is not None and new_func["return_type"] is not None:
                            type_issues.append({
                                "type": "RETURN_TYPE_CHANGE",
                                "message": (f"Return type changed for function '{func_name}': "
                                           f"from '{orig_func['return_type']}' to '{new_func['return_type']}'"),
                                "function": func_name,
                                "is_critical": True
                            })
                        elif orig_func["return_type"] is None and new_func["return_type"] is not None:
                            type_issues.append({
                                "type": "RETURN_TYPE_ADDED",
                                "message": (f"Return type annotation added to function '{func_name}': "
                                           f"'{new_func['return_type']}'"),
                                "function": func_name,
                                "is_critical": False
                            })
                        elif orig_func["return_type"] is not None and new_func["return_type"] is None:
                            type_issues.append({
                                "type": "RETURN_TYPE_REMOVED",
                                "message": (f"Return type annotation removed from function '{func_name}': "
                                           f"was '{orig_func['return_type']}'"),
                                "function": func_name,
                                "is_critical": True
                            })
                    
                    # Check parameter type compatibility
                    orig_params = set(orig_func["parameters"].keys())
                    new_params = set(new_func["parameters"].keys())
                    
                    # Parameters removed
                    for param in orig_params - new_params:
                        if param not in ('self', 'cls'):  # Ignore self/cls parameters
                            type_issues.append({
                                "type": "PARAMETER_REMOVED",
                                "message": f"Parameter '{param}' removed from function '{func_name}'",
                                "function": func_name,
                                "parameter": param,
                                "is_critical": True
                            })
                    
                    # Parameters added
                    for param in new_params - orig_params:
                        if param not in ('self', 'cls'):  # Ignore self/cls parameters
                            # Check if it has a default value (more complex to detect)
                            # For simplicity, we'll assume it doesn't and mark it as critical
                            type_issues.append({
                                "type": "PARAMETER_ADDED",
                                "message": f"New parameter '{param}' added to function '{func_name}'",
                                "function": func_name,
                                "parameter": param,
                                "is_critical": True
                            })
                    
                    # Parameter types changed
                    for param in orig_params.intersection(new_params):
                        orig_type = orig_func["parameters"][param]
                        new_type = new_func["parameters"][param]
                        
                        if orig_type != new_type:
                            if orig_type is not None and new_type is not None:
                                type_issues.append({
                                    "type": "PARAMETER_TYPE_CHANGE",
                                    "message": (f"Type annotation for parameter '{param}' in function '{func_name}' changed: "
                                               f"from '{orig_type}' to '{new_type}'"),
                                    "function": func_name,
                                    "parameter": param,
                                    "is_critical": True
                                })
                            elif orig_type is None and new_type is not None:
                                type_issues.append({
                                    "type": "PARAMETER_TYPE_ADDED",
                                    "message": (f"Type annotation added to parameter '{param}' in function '{func_name}': "
                                               f"'{new_type}'"),
                                    "function": func_name,
                                    "parameter": param,
                                    "is_critical": False
                                })
                            elif orig_type is not None and new_type is None:
                                type_issues.append({
                                    "type": "PARAMETER_TYPE_REMOVED",
                                    "message": (f"Type annotation removed from parameter '{param}' in function '{func_name}': "
                                               f"was '{orig_type}'"),
                                    "function": func_name,
                                    "parameter": param,
                                    "is_critical": True
                                })
            
            # Check for class type annotation changes
            original_classes: dict[str, dict[str, Any]] = {}
            replacement_classes: dict[str, dict[str, Any]] = {}
            
            # Extract classes and their type information
            def extract_class_types(node: ast.ClassDef) -> dict[str, Any]:
                class_types = {
                    "name": node.name,
                    "bases": [],
                    "has_type_annotations": False,
                    "attributes": {}
                }
                
                # Extract base classes
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        class_types["bases"].append(base.id)
                    elif hasattr(ast, 'unparse'):
                        class_types["bases"].append(ast.unparse(base))
                    else:
                        class_types["bases"].append("complex_base")
                
                # Extract typed class attributes
                for node_item in node.body:
                    if isinstance(node_item, ast.AnnAssign) and isinstance(node_item.target, ast.Name):
                        class_types["has_type_annotations"] = True
                        if isinstance(node_item.annotation, ast.Name):
                            class_types["attributes"][node_item.target.id] = node_item.annotation.id
                        elif hasattr(ast, 'unparse'):
                            class_types["attributes"][node_item.target.id] = ast.unparse(node_item.annotation)
                        else:
                            class_types["attributes"][node_item.target.id] = "complex_type"
                            
                return class_types
            
            # Extract classes from original code
            for node in ast.walk(original_ast):
                if isinstance(node, ast.ClassDef):
                    original_classes[node.name] = extract_class_types(node)
            
            # Extract classes from replacement code
            for node in ast.walk(replacement_ast):
                if isinstance(node, ast.ClassDef):
                    replacement_classes[node.name] = extract_class_types(node)
            
            # Compare classes for type compatibility
            for class_name, orig_class in original_classes.items():
                if class_name in replacement_classes:
                    new_class = replacement_classes[class_name]
                    
                    # Check class inheritance compatibility
                    orig_bases = set(orig_class["bases"])
                    new_bases = set(new_class["bases"])
                    
                    # Bases removed
                    for base in orig_bases - new_bases:
                        type_issues.append({
                            "type": "BASE_CLASS_REMOVED",
                            "message": f"Base class '{base}' removed from class '{class_name}'",
                            "class": class_name,
                            "base_class": base,
                            "is_critical": True
                        })
                    
                    # Bases added
                    for base in new_bases - orig_bases:
                        type_issues.append({
                            "type": "BASE_CLASS_ADDED",
                            "message": f"New base class '{base}' added to class '{class_name}'",
                            "class": class_name,
                            "base_class": base,
                            "is_critical": False
                        })
                    
                    # Check attribute type compatibility
                    orig_attrs = set(orig_class["attributes"].keys())
                    new_attrs = set(new_class["attributes"].keys())
                    
                    # Typed attributes removed
                    for attr in orig_attrs - new_attrs:
                        type_issues.append({
                            "type": "TYPED_ATTRIBUTE_REMOVED",
                            "message": f"Typed attribute '{attr}' removed from class '{class_name}'",
                            "class": class_name,
                            "attribute": attr,
                            "is_critical": True
                        })
                    
                    # Attribute types changed
                    for attr in orig_attrs.intersection(new_attrs):
                        orig_type = orig_class["attributes"][attr]
                        new_type = new_class["attributes"][attr]
                        
                        if orig_type != new_type:
                            type_issues.append({
                                "type": "ATTRIBUTE_TYPE_CHANGE",
                                "message": (f"Type annotation for attribute '{attr}' in class '{class_name}' changed: "
                                           f"from '{orig_type}' to '{new_type}'"),
                                "class": class_name,
                                "attribute": attr,
                                "is_critical": True
                            })
            
        except Exception as e:
            # If type checking fails, log the error but don't block the replacement
            type_issues.append({
                "type": "TYPE_CHECK_ERROR",
                "message": f"Failed to perform type compatibility check: {str(e)}",
                "is_critical": False
            })
            
        return type_issues
