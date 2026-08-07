"""Tests for JSON mask signal utilities."""

import pytest

from src.processors._signals.json_mask import (
    JsonToken,
    JsonTokenType,
    _should_preserve_token,
    _tokenize_json,
    compress_json_string,
    compress_json_tokens,
)


class TestTokenizeJson:
    """Test JSON tokenization."""

    def test_empty_string(self):
        tokens = _tokenize_json("")
        assert tokens == []

    def test_simple_object(self):
        tokens = _tokenize_json('{"key": "value"}')
        # Should find: {, "key", :, "value", }
        types = [t.type for t in tokens if t.type != JsonTokenType.WHITESPACE]
        assert JsonTokenType.OBJECT_START in types
        assert JsonTokenType.OBJECT_END in types
        assert JsonTokenType.COLON in types
        assert types.count(JsonTokenType.STRING) == 2

    def test_simple_array(self):
        tokens = _tokenize_json('[1, 2, 3]')
        types = [t.type for t in tokens if t.type != JsonTokenType.WHITESPACE]
        assert JsonTokenType.ARRAY_START in types
        assert JsonTokenType.ARRAY_END in types
        assert types.count(JsonTokenType.NUMBER) == 3

    def test_truncated_json(self):
        # Should handle truncated JSON gracefully
        tokens = _tokenize_json('{"key": "val')
        # Should still tokenize what it can
        assert len(tokens) > 0

    def test_numbers(self):
        tokens = _tokenize_json('{"int": 42, "float": 3.14, "neg": -7, "exp": 1e10}')
        numbers = [t for t in tokens if t.type == JsonTokenType.NUMBER]
        assert len(numbers) == 4

    def test_booleans(self):
        tokens = _tokenize_json('{"a": true, "b": false}')
        booleans = [t for t in tokens if t.type == JsonTokenType.BOOLEAN]
        assert len(booleans) == 2

    def test_null(self):
        tokens = _tokenize_json('{"a": null}')
        nulls = [t for t in tokens if t.type == JsonTokenType.NULL]
        assert len(nulls) == 1

    def test_nested(self):
        tokens = _tokenize_json('{"outer": {"inner": [1, 2]}}')
        obj_starts = [t for t in tokens if t.type == JsonTokenType.OBJECT_START]
        arr_starts = [t for t in tokens if t.type == JsonTokenType.ARRAY_START]
        assert len(obj_starts) == 2
        assert len(arr_starts) == 1

    def test_whitespace(self):
        tokens = _tokenize_json('{ "a" : 1 }')
        ws = [t for t in tokens if t.type == JsonTokenType.WHITESPACE]
        assert len(ws) > 0


class TestShouldPreserveToken:
    """Test token preservation logic."""

    def test_structural_always_preserved(self):
        token = JsonToken(JsonTokenType.OBJECT_START, "{", 0)
        assert _should_preserve_token(token) is True

    def test_important_key_preserved(self):
        token = JsonToken(JsonTokenType.STRING, '"important"', 0)
        assert _should_preserve_token(token, important_key=True) is True

    def test_string_within_depth(self):
        token = JsonToken(JsonTokenType.STRING, '"hello"', 0)
        assert _should_preserve_token(token, depth=0, max_depth=4) is True

    def test_string_beyond_max_depth(self):
        token = JsonToken(JsonTokenType.STRING, '"hello world this is a long string"', 0)
        assert _should_preserve_token(token, depth=5, max_depth=4) is False

    def test_short_string_beyond_max_depth(self):
        token = JsonToken(JsonTokenType.STRING, '"hi"', 0)
        assert _should_preserve_token(token, depth=5, max_depth=4) is True


class TestCompressJsonString:
    """Test JSON string compression."""

    def test_empty(self):
        result = compress_json_string("")
        assert result == ""

    def test_simple_preserved(self):
        json_str = '{"key": "value"}'
        result = compress_json_string(json_str)
        assert "key" in result
        assert "value" in result

    def test_truncated_json_handled(self):
        # Should not crash on truncated JSON
        truncated = '{"key": "val'
        result = compress_json_string(truncated)
        assert isinstance(result, str)


class TestJsonTokenType:
    """Test the token type constants."""

    def test_token_types_are_integers(self):
        assert isinstance(JsonTokenType.OBJECT_START, int)
        assert isinstance(JsonTokenType.STRING, int)

    def test_token_types_are_unique(self):
        types = [
            JsonTokenType.OBJECT_START,
            JsonTokenType.OBJECT_END,
            JsonTokenType.ARRAY_START,
            JsonTokenType.ARRAY_END,
            JsonTokenType.COLON,
            JsonTokenType.COMMA,
            JsonTokenType.STRING,
            JsonTokenType.NUMBER,
            JsonTokenType.BOOLEAN,
            JsonTokenType.NULL,
            JsonTokenType.WHITESPACE,
            JsonTokenType.UNKNOWN,
        ]
        assert len(types) == len(set(types))


class TestJsonToken:
    """Test the JsonToken class."""

    def test_creation(self):
        token = JsonToken(JsonTokenType.STRING, '"hello"', 5)
        assert token.type == JsonTokenType.STRING
        assert token.value == '"hello"'
        assert token.position == 5

    def test_repr(self):
        token = JsonToken(JsonTokenType.STRING, '"hello"', 0)
        repr_str = repr(token)
        assert "STRING" in repr_str
        assert "hello" in repr_str
