from __future__ import annotations

import chardet
from pathlib import Path
from typing import Any
from dataclasses import dataclass


@dataclass
class EncodingInfo:
    encoding: str
    confidence: float
    language: str | None
    

class EncodingDetector:
    def __init__(self) -> None:
        self.common_encodings: list[str] = [
            'utf-8',
            'utf-16',
            'utf-16-le',
            'utf-16-be',
            'ascii',
            'iso-8859-1',
            'windows-1252',
            'shift-jis',
            'euc-jp',
            'gb2312',
            'big5'
        ]

    def detect_encoding(self, content: bytes, sample_size: int = 1024) -> EncodingInfo:
        # First check for BOM
        bom_encoding: str | None = self._check_bom(content)
        if bom_encoding:
            return EncodingInfo(
                encoding=bom_encoding,
                confidence=1.0,
                language=None
            )
        
        # Use chardet for detection
        sample: bytes = content[:sample_size]
        result: dict[str, Any] = chardet.detect(sample)
        
        # Validate encoding
        encoding: str = result.get('encoding', 'utf-8')
        confidence: float = result.get('confidence', 0.0)
        
        # Try common encodings if confidence is low
        if confidence < 0.7:
            for test_encoding in self.common_encodings:
                try:
                    content.decode(test_encoding)
                    return EncodingInfo(
                        encoding=test_encoding,
                        confidence=0.8,
                        language=result.get('language')
                    )
                except UnicodeDecodeError:
                    continue
        
        return EncodingInfo(
            encoding=encoding,
            confidence=confidence,
            language=result.get('language')
        )

    def _check_bom(self, content: bytes) -> str | None:
        # Check for Byte Order Mark
        if content.startswith(b'\xff\xfe\x00\x00'):
            return 'utf-32-le'
        elif content.startswith(b'\x00\x00\xfe\xff'):
            return 'utf-32-be'
        elif content.startswith(b'\xff\xfe'):
            return 'utf-16-le'
        elif content.startswith(b'\xfe\xff'):
            return 'utf-16-be'
        elif content.startswith(b'\xef\xbb\xbf'):
            return 'utf-8-sig'
        
        return None

    def convert_encoding(self, content: bytes, from_encoding: str, 
                        to_encoding: str, errors: str = 'strict') -> bytes:
        # Decode from source encoding
        text: str = content.decode(from_encoding, errors=errors)
        
        # Encode to target encoding
        return text.encode(to_encoding, errors=errors)

    def normalize_line_endings(self, content: bytes, target: str = 'LF') -> bytes:
        # Decode to text
        encoding_info: EncodingInfo = self.detect_encoding(content)
        text: str = content.decode(encoding_info.encoding)
        
        # Normalize line endings
        if target == 'LF':
            text = text.replace('\r\n', '\n').replace('\r', '\n')
        elif target == 'CRLF':
            text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\r\n')
        elif target == 'CR':
            text = text.replace('\r\n', '\n').replace('\n', '\r')
        
        # Encode back
        return text.encode(encoding_info.encoding)

    def detect_file_encoding(self, file_path: Path, sample_size: int = 1024) -> EncodingInfo:
        with open(file_path, 'rb') as f:
            sample: bytes = f.read(sample_size)
        
        return self.detect_encoding(sample)

    def is_binary_file(self, file_path: Path, sample_size: int = 1024) -> bool:
        with open(file_path, 'rb') as f:
            sample: bytes = f.read(sample_size)
        
        # Check for null bytes (common in binary files)
        if b'\x00' in sample:
            return True
        
        # Check if it's valid text in any encoding
        try:
            encoding_info: EncodingInfo = self.detect_encoding(sample)
            if encoding_info.confidence > 0.5:
                sample.decode(encoding_info.encoding)
                return False
        except UnicodeDecodeError:
            pass
        
        return True

    def get_file_info(self, file_path: Path) -> dict[str, Any]:
        is_binary: bool = self.is_binary_file(file_path)
        
        info: dict[str, Any] = {
            'path': str(file_path),
            'is_binary': is_binary,
            'size': file_path.stat().st_size
        }
        
        if not is_binary:
            encoding_info: EncodingInfo = self.detect_file_encoding(file_path)
            info.update({
                'encoding': encoding_info.encoding,
                'confidence': encoding_info.confidence,
                'language': encoding_info.language
            })
        
        return info
