from __future__ import annotations

import ast
import re
import difflib
from pathlib import Path
from typing import Any, List, Tuple

from .base_parser import BaseParser, ParserResult


class PythonParser(BaseParser):
    def __init__(self) -> None:
        super().__init__()
        self.ast_tree: ast.Module | None = None
        self.parent_map: dict[ast.AST, ast.AST] = {}
        self.classes: dict[str, list[str]] = {}
        self.functions: list[str] = []
        
    def find_target(self, content: str, highlight: str | dict[str, Any]) -> ParserResult:
        self.content = content
        self.parent_map.clear()
        
        try:
            self.ast_tree = ast.parse(content)
            for node in ast.walk(self.ast_tree):
                for child in ast.iter_child_nodes(node):
                    self.parent_map[child] = node
        except SyntaxError:
            self.ast_tree = None
            self.parent_map.clear()
        
        # Process different highlight types with robust error handling
        try:
            if isinstance(highlight, str):
                try:
                    return self._find_class_or_method(highlight)
                except ValueError as e:
                    # Find similar targets for suggestions
                    similar_targets = self._find_similar_targets(highlight)
                    available: str = self._list_available_targets()
                    
                    suggestions = ""
                    if similar_targets:
                        suggestions = "\n\nDid you mean one of these?\n- " + "\n- ".join(similar_targets)
                    
                    raise ValueError(f"{str(e)}\n\nAvailable targets:\n{available}{suggestions}")
            
            if isinstance(highlight, dict):
                if "target" in highlight:
                    if isinstance(highlight["target"], list):
                        for target in highlight["target"]:
                            try:
                                result: ParserResult = self._find_class_or_method(target)
                                break
                            except ValueError:
                                continue
                        else:
                            targets_str: str = ", ".join(highlight["target"])
                            available: str = self._list_available_targets()
                            
                            # Find similar targets for all provided targets
                            all_similar_targets = []
                            for target in highlight["target"]:
                                all_similar_targets.extend(self._find_similar_targets(target))
                            
                            suggestions = ""
                            if all_similar_targets:
                                suggestions = "\n\nDid you mean one of these?\n- " + "\n- ".join(all_similar_targets)
                                
                            raise ValueError(f"None of the targets found: {targets_str}.\n\nAvailable targets:\n{available}{suggestions}")
                    else:
                        target: str = highlight["target"]
                        try:
                            result = self._find_class_or_method(target)
                        except ValueError as e:
                            available: str = self._list_available_targets()
                            similar_targets = self._find_similar_targets(target)
                            
                            suggestions = ""
                            if similar_targets:
                                suggestions = "\n\nDid you mean one of these?\n- " + "\n- ".join(similar_targets)
                                
                            raise ValueError(f"{str(e)}\n\nAvailable targets:\n{available}{suggestions}")
                    
                    if "block_start" in highlight and "block_end" in highlight:
                        try:
                            match_type: str = highlight.get("match_type", "exact")
                            return self._find_block(
                                result, 
                                highlight["block_start"], 
                                highlight["block_end"],
                                match_type
                            )
                        except ValueError as e:
                            raise ValueError(f"{str(e)} in {target}")
                    
                    return result
                else:
                    raise ValueError("Missing 'target' key in highlight dictionary. You must specify which class/method to target.")
            
            raise ValueError(
                f"Invalid format for 'highlight' parameter: {highlight}.\n"
                f"Please use a string like 'ClassName' or 'ClassName.method_name'.\n"
                f"Example: highlight='MyClass' or highlight='MyClass.my_method'"
            )
            
        except Exception as e:
            if not isinstance(e, ValueError):
                # Ensure we always return a ValueError with good information
                raise ValueError(f"Error finding target: {str(e)}")
            raise
    
    def apply_replacement(self, content: str, result: ParserResult, replace_with: str) -> str:
        original_block: str = content[result.start_pos:result.end_pos]
        
        # Validate replacement compatibility
        warnings = self._validate_compatibility(original_block, replace_with, result.metadata)
        if warnings:
            import logging
            for warning in warnings:
                logging.warning(f"Compatibility warning: {warning}")
        
        # Preserve decorators
        if result.decorators:
            decorator_text = result.line_ending.join(result.decorators) + result.line_ending
            replace_with = decorator_text + replace_with
            
        # Preserve comments if user didn't include them
        if result.comments_before and not any(c.strip().startswith('#') for c in replace_with.split('\n')[:3]):
            comments_text = result.line_ending.join(result.comments_before) + result.line_ending
            replace_with = comments_text + replace_with
            
        if result.comments_after and not any(c.strip().startswith('#') for c in replace_with.split('\n')[-3:]):
            comments_text = result.line_ending + result.line_ending.join(result.comments_after)
            replace_with = replace_with.rstrip() + result.line_ending + comments_text
        
        # Format with proper indentation
        formatted_replacement: str = self.preserve_indentation(original_block, replace_with)
        
        # Apply the replacement
        new_content: str = content[:result.start_pos] + formatted_replacement + content[result.end_pos:]
        return new_content
        


    def _validate_compatibility(self, original_block: str, new_text: str, metadata: dict) -> list[str]:
        """Validate semantic compatibility between original and replacement code."""
        warnings = []
        
        # Extract method signatures
        orig_sig_match = re.search(r'def\s+(\w+)\s*\((.*?)\)', original_block)
        new_sig_match = re.search(r'def\s+(\w+)\s*\((.*?)\)', new_text)
        
        if orig_sig_match and new_sig_match:
            # Check method name consistency
            orig_name = orig_sig_match.group(1)
            new_name = new_sig_match.group(1)
            if orig_name != new_name:
                warnings.append(f"Method name changed from '{orig_name}' to '{new_name}'")
            
            # Check parameter count
            orig_params = [p.strip() for p in orig_sig_match.group(2).split(',') if p.strip()]
            new_params = [p.strip() for p in new_sig_match.group(2).split(',') if p.strip()]
            
            if len(orig_params) != len(new_params):
                warnings.append(f"Parameter count changed: original had {len(orig_params)}, new has {len(new_params)}")
                
            # Check for removed/renamed parameters
            orig_param_names = [p.split(':')[0].split('=')[0].strip() for p in orig_params]
            new_param_names = [p.split(':')[0].split('=')[0].strip() for p in new_params]
            
            for p in orig_param_names:
                if p not in new_param_names and p != 'self' and p != 'cls':
                    warnings.append(f"Parameter '{p}' removed or renamed")
        
        # Check for super() calls
        if metadata.get('has_super') and 'super()' not in new_text:
            warnings.append("Original code had super() call which is missing in replacement")
            
        # Check for class inheritance changes if bases are in metadata
        if 'bases' in metadata and metadata['bases']:
            bases_str = ', '.join(metadata['bases'])
            
            # Check if any originally extended class is now missing
            for base in metadata['bases']:
                if not re.search(rf'class\s+\w+\s*\([^)]*{re.escape(base)}[^)]*\)', new_text):
                    warnings.append(f"Class inheritance changed: original extended '{base}'")
        
        return warnings
    
    def _list_available_targets(self) -> str:
        """List all available targets in a user-friendly format."""
        self._scan_for_targets()
        
        result: list[str] = []
        for func in self.functions:
            result.append(func)
        
        for cls_name, methods in self.classes.items():
            result.append(cls_name)
            for method in methods:
                result.append(f"{cls_name}.{method}")
        
        # Show all targets instead of truncating
        if result:
            # Sort by name for easier reading
            result.sort()
            # Format in multiple lines for better readability
            if len(result) > 10:
                formatted = "\n- ".join(result)
                return f"- {formatted}"
            else:
                return ", ".join(result)
        else:
            return "none found"
            
    def _find_similar_targets(self, name: str) -> list[str]:
        """Find similar targets using fuzzy matching."""
        self._scan_for_targets()
        
        all_targets: list[str] = []
        for func in self.functions:
            all_targets.append(func)
        
        for cls_name, methods in self.classes.items():
            all_targets.append(cls_name)
            for method in methods:
                all_targets.append(f"{cls_name}.{method}")
        
        # Use difflib to find similar names
        similarities = []
        for target in all_targets:
            ratio = difflib.SequenceMatcher(None, name, target).ratio()
            if ratio > 0.6:  # Threshold for similarity
                similarities.append((target, ratio))
        
        # Sort by similarity ratio
        similarities.sort(key=lambda x: x[1], reverse=True)
        
        # Return up to 5 most similar targets
        return [target for target, _ in similarities[:5]]
    
    def _scan_for_targets(self) -> None:
        self.classes.clear()
        self.functions.clear()
        
        if self.ast_tree:
            for node in ast.walk(self.ast_tree):
                if isinstance(node, ast.ClassDef):
                    methods: list[str] = []
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            methods.append(item.name)
                    self.classes[node.name] = methods
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    parent = self.parent_map.get(node)
                    if parent and isinstance(parent, ast.Module):
                        self.functions.append(node.name)
            return
            
        lines: list[str] = self.content.splitlines()
        current_class: str = ""
        
        for line in lines:
            line_stripped: str = line.strip()
            
            class_match = re.match(r'class\s+([A-Za-z0-9_]+)[\(:]', line_stripped)
            if class_match:
                current_class = class_match.group(1)
                self.classes[current_class] = []
                continue
                
            func_match = re.match(r'(?:async\s+)?def\s+([A-Za-z0-9_]+)\s*\(', line_stripped)
            if func_match:
                func_name: str = func_match.group(1)
                if current_class:
                    self.classes[current_class].append(func_name)
                else:
                    self.functions.append(func_name)
    
    def _find_class_or_method(self, target: str) -> ParserResult:
        indentation: str = ""
        
        if "." in target:
            class_name, method_name = target.split(".")
            
            if self.ast_tree:
                for node in ast.walk(self.ast_tree):
                    if isinstance(node, ast.ClassDef) and node.name == class_name:
                        for item in node.body:
                            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name:
                                start_line: int = item.lineno - 1
                                end_line: int = item.end_lineno if hasattr(item, 'end_lineno') else start_line
                                
                                lines: list[str] = self.content.splitlines()
                                
                                # Collect decorators
                                decorators: list[str] = []
                                i = start_line - 1
                                while i >= 0:
                                    line = lines[i].strip()
                                    if line.startswith('@'):
                                        decorators.insert(0, lines[i])
                                        i -= 1
                                    else:
                                        break
                                
                                # Adjust start line to include decorators
                                if decorators:
                                    start_line -= len(decorators)
                                
                                # Collect comments before
                                comments_before: list[str] = []
                                i = start_line - 1
                                while i >= 0:
                                    line = lines[i].strip()
                                    if line.startswith('#'):
                                        comments_before.insert(0, lines[i])
                                        i -= 1
                                    elif not line:  # Empty line
                                        i -= 1
                                    else:
                                        break
                                
                                # Collect comments after
                                comments_after: list[str] = []
                                i = end_line + 1
                                while i < len(lines):
                                    line = lines[i].strip()
                                    if line.startswith('#'):
                                        comments_after.append(lines[i])
                                        i += 1
                                    elif not line:  # Empty line
                                        i += 1
                                    else:
                                        break
                                
                                # Calculate positions
                                start_pos: int = 0
                                for i in range(start_line):
                                    start_pos += len(lines[i]) + 1
                                
                                end_pos: int = start_pos
                                for i in range(start_line, min(end_line + 1, len(lines))):
                                    end_pos += len(lines[i]) + 1
                                
                                method_line: str = lines[start_line]
                                indentation = method_line[:len(method_line) - len(method_line.lstrip())]
                                
                                # Detect line endings
                                line_ending = '\r\n' if '\r\n' in self.content else '\n'
                                
                                result = ParserResult(
                                    start_pos=start_pos,
                                    end_pos=end_pos,
                                    indentation=indentation,
                                    decorators=decorators,
                                    comments_before=comments_before,
                                    comments_after=comments_after,
                                    line_ending=line_ending
                                )
                                
                                # Store metadata for semantic validation
                                try:
                                    result.metadata['params'] = [a.arg for a in item.args.args]
                                    result.metadata['returns'] = getattr(item, 'returns', None)
                                    result.metadata['has_super'] = self._has_super_call(item)
                                except Exception:
                                    pass
                                
                                return result
            
            return self._find_method_by_string(class_name, method_name)
        
        else:
            if self.ast_tree:
                for node in ast.walk(self.ast_tree):
                    if ((isinstance(node, ast.ClassDef) and node.name == target) or
                        (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and 
                         node.name == target and isinstance(self.parent_map.get(node), ast.Module))):
                        
                        start_line: int = node.lineno - 1
                        end_line: int = node.end_lineno if hasattr(node, 'end_lineno') else start_line
                        
                        lines: list[str] = self.content.splitlines()
                        
                        # Collect decorators
                        decorators: list[str] = []
                        i = start_line - 1
                        while i >= 0:
                            line = lines[i].strip()
                            if line.startswith('@'):
                                decorators.insert(0, lines[i])
                                i -= 1
                            else:
                                break
                        
                        # Adjust start line to include decorators
                        if decorators:
                            start_line -= len(decorators)
                            
                        # Collect comments before and after
                        comments_before: list[str] = []
                        i = start_line - 1
                        while i >= 0:
                            line = lines[i].strip()
                            if line.startswith('#'):
                                comments_before.insert(0, lines[i])
                                i -= 1
                            elif not line:  # Empty line
                                i -= 1
                            else:
                                break
                        
                        comments_after: list[str] = []
                        i = end_line + 1
                        while i < len(lines):
                            line = lines[i].strip()
                            if line.startswith('#'):
                                comments_after.append(lines[i])
                                i += 1
                            elif not line:  # Empty line
                                i += 1
                            else:
                                break
                        
                        # Calculate positions
                        start_pos: int = 0
                        for i in range(start_line):
                            start_pos += len(lines[i]) + 1
                        
                        end_pos: int = start_pos
                        for i in range(start_line, min(end_line + 1, len(lines))):
                            end_pos += len(lines[i]) + 1
                        
                        def_line: str = lines[start_line]
                        indentation = def_line[:len(def_line) - len(def_line.lstrip())]
                        
                        # Detect line endings
                        line_ending = '\r\n' if '\r\n' in self.content else '\n'
                        
                        result = ParserResult(
                            start_pos=start_pos,
                            end_pos=end_pos,
                            indentation=indentation,
                            decorators=decorators,
                            comments_before=comments_before,
                            comments_after=comments_after,
                            line_ending=line_ending
                        )
                        
                        # Store metadata for semantic validation
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            try:
                                result.metadata['params'] = [a.arg for a in node.args.args]
                                result.metadata['returns'] = getattr(node, 'returns', None)
                                result.metadata['has_super'] = self._has_super_call(node)
                            except Exception:
                                pass
                        elif isinstance(node, ast.ClassDef):
                            try:
                                result.metadata['bases'] = [base.id for base in node.bases if hasattr(base, 'id')]
                            except Exception:
                                pass
                                
                        return result
            
            return self._find_class_or_function_by_string(target)
            
    def _has_super_call(self, node: ast.AST) -> bool:
        """Check if a function contains a super() call."""
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if hasattr(child.func, 'id') and child.func.id == 'super':
                    return True
        return False
    
    def _find_method_by_string(self, class_name: str, method_name: str) -> ParserResult:
        lines: list[str] = self.content.splitlines()
        in_class: bool = False
        class_indent: str = ""
        method_start: int = -1
        current_pos: int = 0
        
        for i, line in enumerate(lines):
            line_stripped: str = line.strip()
            
            line_len: int = len(line) + 1
            
            if line_stripped.startswith(f"class {class_name}") and line_stripped[len(class_name)+6] in ["(", ":"]:
                in_class = True
                class_indent = line[:len(line) - len(line.lstrip())]
            
            elif in_class:
                line_indent: str = line[:len(line) - len(line.lstrip())]
                
                if line_stripped and len(line_indent) <= len(class_indent):
                    in_class = False
                
                elif line_stripped.startswith(f"def {method_name}") and line_stripped[len(method_name)+4] in ["(", ":"]:
                    method_start = current_pos
                    method_indent: str = line_indent
                    
                    j: int = i + 1
                    while j < len(lines):
                        next_line: str = lines[j]
                        next_indent: str = next_line[:len(next_line) - len(next_line.lstrip())]
                        
                        if next_line.strip() and len(next_indent) <= len(method_indent):
                            break
                        
                        j += 1
                    
                    method_end: int = current_pos
                    for k in range(i, min(j, len(lines))):
                        method_end += len(lines[k]) + 1
                    
                    return ParserResult(method_start, method_end, method_indent)
            
            current_pos += line_len
        
        raise ValueError(f"Could not find method {method_name} in class {class_name}")
    
    def _find_class_or_function_by_string(self, name: str) -> ParserResult:
        lines: list[str] = self.content.splitlines()
        current_pos: int = 0
        
        # Check if name might include "class" or "def" prefix (common user error)
        actual_name = name
        if name.startswith("class "):
            actual_name = name[6:].strip()  # Remove "class " prefix
        elif name.startswith("def "):
            actual_name = name[4:].strip()  # Remove "def " prefix
        
        # Also check if name ends with a colon or has parentheses (another common error)
        if actual_name.endswith(":"):
            actual_name = actual_name[:-1].strip()
        
        # Remove parentheses if present
        if "(" in actual_name:
            actual_name = actual_name.split("(")[0].strip()
            
        for i, line in enumerate(lines):
            line_stripped: str = line.strip()
            
            line_len: int = len(line) + 1  # +1 for newline
            
            # Check for exact match with the cleaned name
            try:
                # Safer checking with more robust error handling
                is_class_match = (line_stripped.startswith(f"class {actual_name}") and 
                                 (len(line_stripped) == len(f"class {actual_name}") or 
                                  (len(actual_name) + 6 < len(line_stripped) and
                                  line_stripped[len(actual_name)+6] in ["(", ":"]))
                                 ) 
                
                is_func_match = (line_stripped.startswith(f"def {actual_name}") and 
                                (len(line_stripped) == len(f"def {actual_name}") or 
                                 (len(actual_name) + 4 < len(line_stripped) and
                                 line_stripped[len(actual_name)+4] in ["(", ":"]))
                                )
                
                if is_class_match or is_func_match:
                    start_pos: int = current_pos
                    indent: str = line[:len(line) - len(line.lstrip())]
                    
                    j: int = i + 1
                    while j < len(lines):
                        next_line: str = lines[j]
                        next_indent: str = next_line[:len(next_line) - len(next_line.lstrip())]
                        
                        if next_line.strip() and len(next_indent) <= len(indent):
                            break
                        
                        j += 1
                    
                    end_pos: int = current_pos
                    for k in range(i, min(j, len(lines))):
                        end_pos += len(lines[k]) + 1
                    
                    return ParserResult(start_pos, end_pos, indent)
            except IndexError:
                # Safer handling of potential index errors
                pass
            
            current_pos += line_len
        
        # More helpful error message with common mistakes
        if name != actual_name:
            # Let the user know we tried to correct their input
            raise ValueError(
                f"Could not find '{name}' or '{actual_name}'. CORRECT FORMAT: Use 'ClassName' or 'ClassName.method_name'. "
                f"DO NOT include 'class'/'def' keywords, parentheses or colons."
            )
        else:
            raise ValueError(
                f"Could not find '{name}'. CORRECT FORMAT: Use 'ClassName' or 'ClassName.method_name'. "
                f"DO NOT include 'class'/'def' keywords, parentheses or colons."
            )
    
    def _find_block(self, context: ParserResult, block_start: str, block_end: str, match_type: str) -> ParserResult:
        section: str = self.content[context.start_pos:context.end_pos]
        section_lines: list[str] = section.splitlines()
        
        start_line: int = -1
        end_line: int = -1
        
        for i, line in enumerate(section_lines):
            line_stripped: str = line.strip()
            
            if start_line == -1:
                if match_type == "exact" and block_start in line:
                    start_line = i
                elif match_type == "regex":
                    if re.search(block_start, line):
                        start_line = i
                elif match_type == "fuzzy":
                    fuzzy_line: str = ''.join(line_stripped.lower().split())
                    fuzzy_target: str = ''.join(block_start.lower().split())
                    if fuzzy_target in fuzzy_line:
                        start_line = i
            
            elif end_line == -1:
                if match_type == "exact" and block_end in line:
                    end_line = i
                elif match_type == "regex":
                    if re.search(block_end, line):
                        end_line = i
                elif match_type == "fuzzy":
                    fuzzy_line: str = ''.join(line_stripped.lower().split())
                    fuzzy_target: str = ''.join(block_end.lower().split())
                    if fuzzy_target in fuzzy_line:
                        end_line = i
        
        if start_line == -1 or end_line == -1:
            raise ValueError(f"Could not find block from '{block_start}' to '{block_end}'")
        
        block_start_pos: int = context.start_pos
        for i in range(start_line):
            block_start_pos += len(section_lines[i]) + 1
        
        block_end_pos: int = context.start_pos
        for i in range(end_line + 1):
            block_end_pos += len(section_lines[i]) + 1
        
        start_line_text: str = section_lines[start_line]
        indentation: str = start_line_text[:len(start_line_text) - len(start_line_text.lstrip())]
        
        return ParserResult(block_start_pos, block_end_pos, indentation)