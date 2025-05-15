from __future__ import annotations

from pathlib import Path
from .base_parser import BaseParser
from .python_parser import PythonParser
from .latex_parser import LaTeXParser


def get_parser_for_file(file_path: Path) -> BaseParser:
    file_ext: str = file_path.suffix.lower()
    
    if file_ext == '.py':
        return PythonParser()
    elif file_ext == '.tex':
        return LaTeXParser()
    else:
        raise ValueError(f"Unsupported file type: {file_ext}")
