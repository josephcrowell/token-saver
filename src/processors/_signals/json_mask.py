"""JSON structure-preserving compression utilities.

Ported from headroom handlers/json_handler.py.
Provides hand-rolled JSON tokenization for truncated/partial JSON handling,
with rules for which tokens to preserve during compression.
"""

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

# Token types for the hand-rolled JSON tokenizer
class JsonTokenType:
    """Token type identifiers for JSON parsing."""
    OBJECT_START = 0    # {
    OBJECT_END = 1      # }
    ARRAY_START = 2     # [
    ARRAY_END = 3       # ]
    COLON = 4           # :
    COMMA = 5           # ,
    STRING = 6          # "..."
    NUMBER = 7          # 123, -4.56, 1e10
    BOOLEAN = 8         # true, false
    NULL = 9            # null
    WHITESPACE = 10     # spaces, tabs, newlines
    UNKNOWN = 11        # parsing errors


# Token structure
class JsonToken:
    """Represents a single token in JSON with its type, value, and position."""
    
    def __init__(self, token_type: int, value: str, position: int):
        self.type = token_type
        self.value = value
        self.position = position
    
    def __repr__(self):
        type_names = {
            JsonTokenType.OBJECT_START: "OBJ_START",
            JsonTokenType.OBJECT_END: "OBJ_END", 
            JsonTokenType.ARRAY_START: "ARR_START",
            JsonTokenType.ARRAY_END: "ARR_END",
            JsonTokenType.COLON: "COLON",
            JsonTokenType.COMMA: "COMMA",
            JsonTokenType.STRING: "STRING",
            JsonTokenType.NUMBER: "NUMBER",
            JsonTokenType.BOOLEAN: "BOOLEAN",
            JsonTokenType.NULL: "NULL",
            JsonTokenType.WHITESPACE: "WS",
            JsonTokenType.UNKNOWN: "UNKNOWN",
        }
        return f"JsonToken({type_names.get(self.type, 'UNKNOWN')}, {self.value!r}, pos={self.position})"


# Configuration constants
SHORT_VALUE_THRESHOLD = 20  # Strings shorter than this are always preserved
MAX_ARRAY_ITEMS_FULL = 3    # Max array items to keep fully before summarizing
MAX_NUMBER_DIGITS = 10      # Max digits to preserve in long numbers


# Patterns for tokenization
_STRING_PATTERN = re.compile(r'"(?:\\.|[^"\\])*"')
_NUMBER_PATTERN = re.compile(r'-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?')
_BOOLEAN_PATTERN = re.compile(r'\b(?:true|false)\b')
_NULL_PATTERN = re.compile(r'\bnull\b')


def _tokenize_json(json_string: str) -> list[JsonToken]:
    """Tokenize a JSON string using hand-rolled state machine.
    
    Ported from headroom json_handler.py::_tokenize_json (L254–390).
    Handles truncated/partial JSON gracefully unlike json.loads().
    
    Args:
        json_string: JSON string to tokenize (may be partial/truncated)
        
    Returns:
        List of JsonToken objects in order
    """
    tokens: list[JsonToken] = []
    pos = 0
    length = len(json_string)
    
    while pos < length:
        char = json_string[pos]
        
        # Skip whitespace
        if char.isspace():
            start = pos
            while pos < length and json_string[pos].isspace():
                pos += 1
            tokens.append(JsonToken(JsonTokenType.WHITESPACE, json_string[start:pos], start))
            continue
        
        # String tokens
        if char == '"':
            match = _STRING_PATTERN.match(json_string, pos)
            if match:
                tokens.append(JsonToken(JsonTokenType.STRING, match.group(), pos))
                pos = match.end()
            else:
                # Malformed string, treat as unknown
                tokens.append(JsonToken(JsonTokenType.UNKNOWN, char, pos))
                pos += 1
            continue
        
        # Number tokens
        if char.isdigit() or char == '-':
            match = _NUMBER_PATTERN.match(json_string, pos)
            if match:
                tokens.append(JsonToken(JsonTokenType.NUMBER, match.group(), pos))
                pos = match.end()
            else:
                tokens.append(JsonToken(JsonTokenType.UNKNOWN, char, pos))
                pos += 1
            continue
        
        # Boolean tokens
        if char in 'tf':
            match = _BOOLEAN_PATTERN.match(json_string, pos)
            if match:
                tokens.append(JsonToken(JsonTokenType.BOOLEAN, match.group(), pos))
                pos = match.end()
            else:
                tokens.append(JsonToken(JsonTokenType.UNKNOWN, char, pos))
                pos += 1
            continue
        
        # Null token
        if char == 'n':
            match = _NULL_PATTERN.match(json_string, pos)
            if match:
                tokens.append(JsonToken(JsonTokenType.NULL, match.group(), pos))
                pos = match.end()
            else:
                tokens.append(JsonToken(JsonTokenType.UNKNOWN, char, pos))
                pos += 1
            continue
        
        # Structural characters
        if char == '{':
            tokens.append(JsonToken(JsonTokenType.OBJECT_START, char, pos))
            pos += 1
            continue
        if char == '}':
            tokens.append(JsonToken(JsonTokenType.OBJECT_END, char, pos))
            pos += 1
            continue
        if char == '[':
            tokens.append(JsonToken(JsonTokenType.ARRAY_START, char, pos))
            pos += 1
            continue
        if char == ']':
            tokens.append(JsonToken(JsonTokenType.ARRAY_END, char, pos))
            pos += 1
            continue
        if char == ':':
            tokens.append(JsonToken(JsonTokenType.COLON, char, pos))
            pos += 1
            continue
        if char == ',':
            tokens.append(JsonToken(JsonTokenType.COMMA, char, pos))
            pos += 1
            continue
        
        # Unknown character
        tokens.append(JsonToken(JsonTokenType.UNKNOWN, char, pos))
        pos += 1
    
    return tokens


def _should_preserve_token(
    token: JsonToken,
    depth: int = 0,
    max_depth: int = 4,
    important_key: bool = False,
    in_array: bool = False,
    array_index: int = 0
) -> bool:
    """Determine if a JSON token should be preserved during compression.
    
    Ported from headroom json_handler.py::_should_preserve_token (L196–252).
    
    Args:
        token: The token to evaluate
        depth: Current nesting depth
        max_depth: Maximum depth to preserve
        important_key: Whether this is an important key (from important_key_re)
        in_array: Whether we're inside an array
        array_index: Index within the array (0-based)
        
    Returns:
        True if token should be preserved
    """
    # Always preserve structural tokens
    if token.type in (
        JsonTokenType.OBJECT_START, JsonTokenType.OBJECT_END,
        JsonTokenType.ARRAY_START, JsonTokenType.ARRAY_END,
        JsonTokenType.COLON, JsonTokenType.COMMA
    ):
        return True
    
    # Preserve important keys at any depth
    if important_key and token.type == JsonTokenType.STRING:
        return True
    
    # Depth-based preservation
    if depth >= max_depth:
        # Beyond max depth, only preserve short strings
        if token.type == JsonTokenType.STRING and len(token.value) <= SHORT_VALUE_THRESHOLD:
            return True
        return False
    
    # Array item preservation
    if in_array and array_index >= MAX_ARRAY_ITEMS_FULL:
        # Beyond max array items, only preserve short values
        if token.type == JsonTokenType.STRING and len(token.value) <= SHORT_VALUE_THRESHOLD:
            return True
        if token.type == JsonTokenType.NUMBER:
            # Preserve short numbers, truncate long ones
            if len(token.value) <= MAX_NUMBER_DIGITS:
                return True
            return False
        return False
    
    # Default: preserve everything within depth limits
    return True


def compress_json_tokens(
    tokens: list[JsonToken],
    max_depth: int = 4,
    important_keys: set[str] | None = None
) -> str:
    """Compress JSON by selectively removing tokens based on rules.
    
    Args:
        tokens: Tokenized JSON from _tokenize_json
        max_depth: Maximum nesting depth to preserve
        important_keys: Set of important keys to preserve at any depth
        
    Returns:
        Compressed JSON string
    """
    if not tokens:
        return ""
    
    important_keys = important_keys or set()
    result: list[str] = []
    
    # Track parsing state
    depth = 0
    in_array = False
    array_depth = 0  # Track depth of arrays separately
    array_indices = [0]  # Array index at each array depth
    
    i = 0
    while i < len(tokens):
        token = tokens[i]
        
        # Check if this is an important key (string before colon)
        is_important_key = False
        if token.type == JsonTokenType.STRING and i + 1 < len(tokens):
            next_token = tokens[i + 1]
            if next_token.type == JsonTokenType.COLON:
                # This is a key, check if important
                key_value = token.value.strip('"')
                if key_value in important_keys:
                    is_important_key = True
        
        # Determine if we should preserve this token
        array_index = array_indices[-1] if array_indices else 0
        should_preserve = _should_preserve_token(
            token, depth, max_depth, is_important_key, in_array, array_index
        )
        
        if should_preserve:
            result.append(token.value)
        
        # Update parsing state
        if token.type == JsonTokenType.OBJECT_START or token.type == JsonTokenType.ARRAY_START:
            depth += 1
            if token.type == JsonTokenType.ARRAY_START:
                in_array = True
                array_depth += 1
                array_indices.append(0)
        elif token.type == JsonTokenType.OBJECT_END or token.type == JsonTokenType.ARRAY_END:
            depth = max(0, depth - 1)
            if token.type == JsonTokenType.ARRAY_END:
                array_depth = max(0, array_depth - 1)
                if len(array_indices) > 1:
                    array_indices.pop()
                in_array = array_depth > 0
        elif token.type == JsonTokenType.COMMA and in_array:
            # Increment array index
            if array_indices:
                array_indices[-1] += 1
        
        i += 1
    
    return "".join(result)


def compress_json_string(
    json_string: str,
    max_depth: int = 4,
    important_keys: set[str] | None = None
) -> str:
    """Compress a JSON string using structure-preserving tokenization.
    
    Args:
        json_string: JSON string to compress (may be partial/truncated)
        max_depth: Maximum nesting depth to preserve fully
        important_keys: Set of important keys to preserve at any depth
        
    Returns:
        Compressed JSON string
    """
    tokens = _tokenize_json(json_string)
    return compress_json_tokens(tokens, max_depth, important_keys)