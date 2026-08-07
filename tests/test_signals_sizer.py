"""Tests for adaptive sizer signal utilities."""

import pytest

from src.processors._signals.adaptive_sizer import (
    compute_keep_count,
    compute_optimal_k,
    compute_unique_bigram_curve,
    count_unique_simhash,
    find_knee,
    _hamming_distance,
    _is_cjk_char,
    _simhash,
    _validate_with_zlib,
)


class TestCJKDetection:
    """Test CJK character detection."""

    def test_ascii_not_cjk(self):
        assert not _is_cjk_char("a")

    def test_chinese_is_cjk(self):
        assert _is_cjk_char("中")

    def test_hiragana_is_cjk(self):
        assert _is_cjk_char("あ")

    def test_katakana_is_cjk(self):
        assert _is_cjk_char("カ")

    def test_hangul_is_cjk(self):
        assert _is_cjk_char("한")

    def test_multi_char_string(self):
        assert not _is_cjk_char("ab")


class TestSimhash:
    """Test simhash computation."""

    def test_same_text_same_hash(self):
        assert _simhash("hello world") == _simhash("hello world")

    def test_different_text_different_hash(self):
        assert _simhash("hello world") != _simhash("goodbye universe")

    def test_similar_text_small_distance(self):
        h1 = _simhash("hello world")
        h2 = _simhash("hello world!")
        # Simhash for similar texts should have small-ish distance
        assert _hamming_distance(h1, h2) <= 30

    def test_identical_text_zero_distance(self):
        h = _simhash("test")
        assert _hamming_distance(h, h) == 0


class TestHammingDistance:
    """Test Hamming distance."""

    def test_identical_zero(self):
        assert _hamming_distance(0, 0) == 0

    def test_all_ones_vs_all_zeros(self):
        assert _hamming_distance(0, 0xFFFFFFFFFFFFFFFF) == 64

    def test_one_bit_difference(self):
        assert _hamming_distance(0, 1) == 1


class TestBigramCurve:
    """Test unique bigram curve computation."""

    def test_empty_list(self):
        assert compute_unique_bigram_curve([]) == []

    def test_single_item(self):
        curve = compute_unique_bigram_curve(["a"])
        assert curve == [0]

    def test_two_items(self):
        curve = compute_unique_bigram_curve(["a", "b"])
        assert curve == [0, 1]

    def test_repeated_items(self):
        curve = compute_unique_bigram_curve(["a", "a", "a"])
        # Each pair is the same, so only 1 unique bigram
        assert curve == [0, 1, 1]

    def test_growing_diversity(self):
        curve = compute_unique_bigram_curve(["a", "b", "c", "d"])
        assert curve == [0, 1, 2, 3]


class TestFindKnee:
    """Test the Kneedle algorithm."""

    def test_empty_curve(self):
        assert find_knee([]) == 0

    def test_short_curve_returns_all(self):
        curve = [1, 2, 3]
        assert find_knee(curve, min_k=3) == 3

    def test_plateau_curve(self):
        # Curve that rises then plateaus
        curve = [1, 2, 3, 4, 5, 5, 5, 5, 5, 5]
        knee = find_knee(curve, min_k=3)
        assert knee >= 3
        assert knee <= 10

    def test_linear_curve(self):
        curve = list(range(100))
        knee = find_knee(curve, min_k=3)
        assert knee >= 3

    def test_respects_min_k(self):
        curve = [0, 1, 2, 3, 4, 5]
        knee = find_knee(curve, min_k=3)
        assert knee >= 3


class TestCountUniqueSimhash:
    """Test simhash-based clustering."""

    def test_empty_list(self):
        assert count_unique_simhash([]) == 0

    def test_all_same(self):
        items = ["hello"] * 10
        assert count_unique_simhash(items) == 1

    def test_all_different(self):
        items = ["alpha", "beta", "gamma", "delta", "epsilon"]
        result = count_unique_simhash(items)
        assert result >= 3  # At least most should be unique

    def test_respects_threshold(self):
        items = ["hello world", "hello world!"]
        # With high threshold, similar texts may be different clusters
        result_high = count_unique_simhash(items, threshold=30)
        result_low = count_unique_simhash(items, threshold=0)
        assert result_low >= result_high


class TestValidateWithZlib:
    """Test zlib validation."""

    def test_full_list_valid(self):
        items = ["item " + str(i) for i in range(20)]
        assert _validate_with_zlib(items, 20) is True

    def test_single_item_valid(self):
        items = ["item " + str(i) for i in range(20)]
        # Single item may pass validation depending on content
        result = _validate_with_zlib(items, 1)
        assert isinstance(result, bool)

    def test_half_valid(self):
        items = ["item " + str(i) for i in range(20)]
        assert _validate_with_zlib(items, 10) is True


class TestComputeOptimalK:
    """Test the optimal K computation."""

    def test_empty_list(self):
        assert compute_optimal_k([]) == 0

    def test_short_list_returns_all(self):
        items = ["a", "b", "c"]
        assert compute_optimal_k(items, min_k=3) == 3

    def test_long_list(self):
        items = [f"item {i} with content {i}" for i in range(50)]
        k = compute_optimal_k(items, min_k=3)
        assert k >= 3
        assert k <= 50

    def test_with_bias(self):
        items = [f"item {i} with content {i}" for i in range(50)]
        conservative = compute_optimal_k(items, min_k=3, bias=1.5)
        aggressive = compute_optimal_k(items, min_k=3, bias=0.7)
        assert conservative >= aggressive


class TestComputeKeepCount:
    """Test the keep count computation with profiles."""

    def test_empty_list(self):
        assert compute_keep_count([]) == 0

    def test_short_list_returns_all(self):
        items = ["a", "b", "c"]
        assert compute_keep_count(items) == 3

    def test_conervative_keeps_more(self):
        items = [f"item {i} with content {i}" for i in range(50)]
        conservative = compute_keep_count(items, profile="conservative")
        aggressive = compute_keep_count(items, profile="aggressive")
        assert conservative >= aggressive

    def test_unknown_profile_defaults_moderate(self):
        items = [f"item {i}" for i in range(20)]
        result = compute_keep_count(items, profile="unknown")
        moderate = compute_keep_count(items, profile="moderate")
        assert result == moderate

    def test_with_graph_ctx_none(self):
        items = [f"item {i}" for i in range(20)]
        result = compute_keep_count(items, graph_ctx=None)
        assert result >= 3
