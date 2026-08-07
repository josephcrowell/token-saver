"""Tests for cross-turn dedup signal utilities."""

import pytest

from src.processors._signals.cross_turn import (
    DEFAULT_MIN_CHARS,
    DEFAULT_MIN_LINES,
    MAX_ANCHOR_CANDIDATES,
    DedupBlock,
    DedupStats,
    dedup_blocks,
    fuzzy_dedup_pass,
    is_prefix_monotonic,
)


class TestDedupBlock:
    """Test the DedupBlock dataclass."""

    def test_creation(self):
        block = DedupBlock(text="hello", turn=1)
        assert block.text == "hello"
        assert block.turn == 1

    def test_equality(self):
        b1 = DedupBlock(text="hello", turn=1)
        b2 = DedupBlock(text="hello", turn=1)
        assert b1 == b2


class TestDedupStats:
    """Test the DedupStats dataclass."""

    def test_defaults(self):
        stats = DedupStats()
        assert stats.spans_folded == 0
        assert stats.chars_saved == 0
        assert stats.exact_folds == 0
        assert stats.fuzzy_folded == 0


class TestDedupBlocks:
    """Test the dedup_blocks function."""

    def test_empty_blocks(self):
        blocks, stats = dedup_blocks([])
        assert blocks == []
        assert stats.spans_folded == 0

    def test_single_block(self):
        block = DedupBlock(text="single block", turn=1)
        blocks, stats = dedup_blocks([block])
        assert len(blocks) == 1
        assert stats.spans_folded == 0

    def test_no_match(self):
        block1 = DedupBlock(text="unique content one\nline two\nline three\nline four", turn=1)
        block2 = DedupBlock(text="completely different\nline two\nline three\nline four", turn=2)
        blocks, stats = dedup_blocks([block1, block2])
        assert stats.spans_folded == 0
        assert blocks[-1].text == block2.text

    def test_exact_match_folded(self):
        content = (
            "This is a long line one with enough characters\n"
            "This is a long line two with enough chars\n"
            "This is a long line three with enough chars\n"
            "This is a long line four with enough chars"
        )
        block1 = DedupBlock(text=content, turn=1)
        block2 = DedupBlock(text=content, turn=2)
        blocks, stats = dedup_blocks([block1, block2])
        assert stats.spans_folded == 1
        assert stats.exact_folds == 1
        assert "↑4L same as msg 1" in blocks[-1].text

    def test_prefix_monotonicity_unchanged_earlier(self):
        content1 = "line one with enough characters to match\nline two with enough chars"
        content2 = content1 + "\nline three with enough chars"
        block1 = DedupBlock(text=content1, turn=1)
        block2 = DedupBlock(text=content2, turn=2)
        blocks, stats = dedup_blocks([block1, block2])
        # First block should be unchanged
        assert blocks[0].text == content1

    def test_min_lines_threshold(self):
        # Content too short (only 2 lines)
        content = "short line one\nshort line two"
        block1 = DedupBlock(text=content, turn=1)
        block2 = DedupBlock(text=content, turn=2)
        blocks, stats = dedup_blocks([block1, block2], min_lines=3)
        assert stats.spans_folded == 0

    def test_min_chars_threshold(self):
        # Content has enough lines but not enough chars
        content = "ab\ncd\nef\ngh\nij"
        block1 = DedupBlock(text=content, turn=1)
        block2 = DedupBlock(text=content, turn=2)
        blocks, stats = dedup_blocks([block1, block2], min_chars=100)
        assert stats.spans_folded == 0

    def test_partial_match(self):
        common = (
            "This is a long common line one with enough chars\n"
            "This is a long common line two with enough chars\n"
            "This is a long common line three with enough chars"
        )
        block1 = DedupBlock(text=common, turn=1)
        block2 = DedupBlock(text=common + "\nNew unique line here", turn=2)
        blocks, stats = dedup_blocks([block1, block2])
        assert stats.spans_folded == 1
        assert "↑3L same as msg 1" in blocks[-1].text
        assert "New unique line here" in blocks[-1].text


class TestIsPrefixMonotonic:
    """Test prefix monotonicity checking."""

    def test_empty(self):
        assert is_prefix_monotonic([]) is True

    def test_single_block(self):
        assert is_prefix_monotonic([DedupBlock(text="a", turn=1)]) is True

    def test_monotonic(self):
        b1 = DedupBlock(text="line1\nline2", turn=1)
        b2 = DedupBlock(text="line1\nline2\nline3", turn=2)
        assert is_prefix_monotonic([b1, b2]) is True

    def test_not_monotonic(self):
        b1 = DedupBlock(text="line1\nline2\nline3", turn=1)
        b2 = DedupBlock(text="line1\nline2", turn=2)
        assert is_prefix_monotonic([b1, b2]) is False

    def test_different_content(self):
        b1 = DedupBlock(text="line1\nline2", turn=1)
        b2 = DedupBlock(text="line3\nline4", turn=2)
        assert is_prefix_monotonic([b1, b2]) is False


class TestFuzzyDedup:
    """Test the fuzzy dedup pass."""

    def test_empty_blocks(self):
        blocks, stats = fuzzy_dedup_pass([])
        assert len(blocks) == 0
        assert stats.fuzzy_folded == 0

    def test_single_block(self):
        blocks, stats = fuzzy_dedup_pass([DedupBlock(text="test", turn=1)])
        assert len(blocks) == 1
        assert stats.fuzzy_folded == 0

    def test_fail_open_no_graphify(self):
        # Without graphify installed, should fail open gracefully
        block1 = DedupBlock(text="test content one\n" * 10, turn=1)
        block2 = DedupBlock(text="test content two\n" * 10, turn=2)
        blocks, stats = fuzzy_dedup_pass([block1, block2])
        assert len(blocks) == 2
        assert stats.fuzzy_folded == 0

    def test_too_many_blocks_skipped(self):
        blocks = [DedupBlock(text=f"content {i}\n" * 10, turn=i) for i in range(250)]
        result, stats = fuzzy_dedup_pass(blocks, max_blocks=200)
        assert stats.fuzzy_folded == 0


class TestConstants:
    """Test that constants are correctly defined."""

    def test_default_min_lines(self):
        assert DEFAULT_MIN_LINES == 3

    def test_default_min_chars(self):
        assert DEFAULT_MIN_CHARS == 40

    def test_max_anchor_candidates(self):
        assert MAX_ANCHOR_CANDIDATES == 16
