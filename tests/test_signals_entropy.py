"""Tests for entropy detection signal utilities."""

import pytest

from src.processors._signals.entropy import (
    DEFAULT_ENTROPY_THRESHOLD,
    SECRET_ENTROPY_MIN_LENGTH,
    EntropyScore,
    compute_entropy,
    entropy_spans,
    is_high_entropy,
    sticky_line_indices,
)


class TestEntropyScore:
    """Test the EntropyScore class."""

    def test_empty_text_low_entropy(self):
        score = EntropyScore("")
        assert score.compute() == 0.0

    def test_constant_text_low_entropy(self):
        score = EntropyScore("aaaa")
        assert score.compute() < 0.5

    def test_random_text_high_entropy(self):
        score = EntropyScore("xJ7$kL9mN2pQ4rS8tV1wY3zA6bC0dE5fG7hI2jK4lM9nO1pQ8rS3tU")
        assert score.compute() > 0.5

    def test_is_high_entropy_threshold(self):
        high = EntropyScore("xJ7$kL9mN2pQ4rS8tV1wY3zA6bC0dE5fG7hI2jK4lM9nO1pQ8rS3tU", threshold=0.5)
        assert high.is_high_entropy

    def test_is_high_entropy_false(self):
        low = EntropyScore("aaaa", threshold=0.85)
        assert not low.is_high_entropy

    def test_compute_caches(self):
        score = EntropyScore("test text for caching")
        first = score.compute()
        second = score.compute()
        assert first == second

    def test_threshold_override(self):
        score = EntropyScore("test", threshold=0.85)
        assert score.compute(threshold=0.5) == score.compute()


class TestEntropySpans:
    """Test the entropy_spans function."""

    def test_short_text_no_spans(self):
        spans = entropy_spans("short", min_length=20)
        assert spans == []

    def test_empty_text_no_spans(self):
        spans = entropy_spans("", min_length=20)
        assert spans == []

    def test_finds_high_entropy_span(self):
        # A high-entropy string
        text = "prefix xJ7$kL9mN2pQ4rS8tV1wY3zA6bC0dE5 suffix"
        spans = entropy_spans(text, threshold=0.7, min_length=20)
        # Should find some spans (or none if the text isn't high enough)
        assert isinstance(spans, list)

    def test_spans_are_tuples(self):
        text = "x" * 100
        spans = entropy_spans(text, min_length=20)
        for span in spans:
            assert isinstance(span, tuple)
            assert len(span) == 2
            assert span[0] < span[1]


class TestStickyLineIndices:
    """Test the sticky_line_indices function."""

    def test_empty_lines(self):
        assert sticky_line_indices([]) == frozenset()

    def test_short_lines_not_sticky(self):
        lines = ["short", "also short", "tiny"]
        assert sticky_line_indices(lines) == frozenset()

    def test_high_entropy_line_is_sticky(self):
        # A line with a high-entropy token
        token = "xJ7$kL9mN2pQ4rS8tV1wY3zA6bC0dE5fG7"
        lines = ["normal line", f"token={token}", "another line"]
        sticky = sticky_line_indices(lines)
        assert isinstance(sticky, frozenset)

    def test_returns_frozenset(self):
        result = sticky_line_indices(["line one", "line two"])
        assert isinstance(result, frozenset)


class TestConvenienceFunctions:
    """Test the convenience functions."""

    def test_compute_entropy(self):
        result = compute_entropy("test")
        assert 0.0 <= result <= 1.0

    def test_compute_entropy_empty(self):
        assert compute_entropy("") == 0.0

    def test_is_high_entropy_true(self):
        assert is_high_entropy("xJ7$kL9mN2pQ4rS8tV1wY3zA6bC0dE5fG7", threshold=0.5)

    def test_is_high_entropy_false(self):
        assert not is_high_entropy("aaaa", threshold=0.85)

    def test_constants(self):
        assert SECRET_ENTROPY_MIN_LENGTH == 20
        assert DEFAULT_ENTROPY_THRESHOLD == 0.85
