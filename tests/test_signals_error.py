"""Tests for error detection signal utilities."""

import pytest

from src.processors._signals.error_detection import (
    ERROR_INDICATOR_KEYWORDS,
    ERROR_KEYWORDS,
    ERROR_PATTERN,
    IMPORTANCE_KEYWORDS,
    SECURITY_KEYWORDS,
    WARNING_KEYWORDS,
    content_has_strong_error_indicators,
    has_error_keywords,
    has_importance_keywords,
    has_security_keywords,
    has_warning_keywords,
    rank_lines,
    score_line,
    scrub_zero_result_patterns,
)


class TestKeywordSets:
    """Test that keyword sets are correctly defined."""

    def test_error_keywords_count(self):
        assert len(ERROR_KEYWORDS) == 13

    def test_warning_keywords_count(self):
        assert len(WARNING_KEYWORDS) == 2

    def test_importance_keywords_count(self):
        assert len(IMPORTANCE_KEYWORDS) == 8

    def test_security_keywords_count(self):
        assert len(SECURITY_KEYWORDS) == 4

    def test_error_indicator_keywords_count(self):
        assert len(ERROR_INDICATOR_KEYWORDS) == 7

    def test_error_keywords_are_frozenset(self):
        assert isinstance(ERROR_KEYWORDS, frozenset)

    def test_error_keywords_contains_expected(self):
        assert "error" in ERROR_KEYWORDS
        assert "exception" in ERROR_KEYWORDS
        assert "timeout" in ERROR_KEYWORDS


class TestContentHasStrongErrorIndicators:
    """Test the strong error indicator detection."""

    def test_no_indicators(self):
        assert not content_has_strong_error_indicators("All systems operational")

    def test_single_indicator(self):
        assert not content_has_strong_error_indicators("There was an error in processing")

    def test_two_distinct_indicators(self):
        assert content_has_strong_error_indicators("error: traceback occurred")

    def test_three_distinct_indicators(self):
        assert content_has_strong_error_indicators(
            "fatal: crash with traceback at line 5"
        )

    def test_zero_result_scrubbing(self):
        assert not content_has_strong_error_indicators("no errors found")

    def test_zero_result_no_warnings(self):
        assert not content_has_strong_error_indicators("no warnings found")

    def test_empty_text(self):
        assert not content_has_strong_error_indicators("")

    def test_same_keyword_twice_not_strong(self):
        # Same keyword repeated should not count as 2 distinct
        assert not content_has_strong_error_indicators("error error error")


class TestScoreLine:
    """Test the line scoring function."""

    def test_error_line_scores_high(self):
        category, score = score_line("ERROR: something went wrong")
        assert category == "error"
        assert score == 1.0

    def test_warning_line_scores_medium(self):
        category, score = score_line("WARNING: deprecated function")
        assert category == "warning"
        assert score == 0.5

    def test_importance_line_scores_low(self):
        category, score = score_line("TODO: fix this later")
        assert category == "importance"
        assert score == 0.3

    def test_security_line_scores_high(self):
        category, score = score_line("Security: password exposed")
        assert category == "security"
        assert score == 0.85

    def test_normal_line_scores_zero(self):
        category, score = score_line("Building project...")
        assert category is None
        assert score == 0.0

    def test_stack_trace_bonus(self):
        category, score = score_line("ERROR: at File \"test.py\" line 10")
        assert category == "error"
        assert score == 1.0  # capped at 1.0

    def test_summary_bonus(self):
        category, score = score_line("ERROR: summary: total failures")
        assert category == "error"
        assert score == 1.0  # capped at 1.0

    def test_empty_line(self):
        category, score = score_line("")
        assert category is None
        assert score == 0.0

    def test_unknown_context_fail_open(self):
        category, score = score_line("ERROR: test", context="unknown_context")
        assert category == "error"
        assert score == 1.0


class TestQuickChecks:
    """Test the quick keyword check functions."""

    def test_has_error_keywords_true(self):
        assert has_error_keywords("an error occurred")

    def test_has_error_keywords_false(self):
        assert not has_error_keywords("all good")

    def test_has_warning_keywords_true(self):
        assert has_warning_keywords("warning: low disk")

    def test_has_importance_keywords_true(self):
        assert has_importance_keywords("TODO: implement")

    def test_has_security_keywords_true(self):
        assert has_security_keywords("auth token expired")


class TestScrubZeroResult:
    """Test the zero-result pattern scrubbing."""

    def test_scrub_no_errors(self):
        # Pattern should match "no errors" type phrases
        result = scrub_zero_result_patterns("no errors")
        assert isinstance(result, str)

    def test_scrub_zero_results(self):
        result = scrub_zero_result_patterns("zero results")
        assert isinstance(result, str)

    def test_scrub_empty_results(self):
        result = scrub_zero_result_patterns("empty results")
        assert isinstance(result, str)

    def test_scrub_no_match_keeps_text(self):
        result = scrub_zero_result_patterns("5 errors found")
        assert "5 errors found" in result


class TestRankLines:
    """Test the line ranking with optional graph context."""

    def test_rank_lines_without_graph(self):
        lines = ["ERROR: bad", "OK", "WARNING: hmm"]
        scores = rank_lines(lines)
        assert len(scores) == 3
        assert scores[0] > scores[1]  # Error > OK
        assert scores[2] > scores[1]  # Warning > OK

    def test_rank_lines_with_none_graph(self):
        lines = ["ERROR: bad", "OK"]
        scores = rank_lines(lines, graph_ctx=None)
        assert len(scores) == 2

    def test_rank_lines_empty(self):
        scores = rank_lines([])
        assert scores == []

    def test_rank_lines_graph_unavailable(self):
        class FakeCtx:
            def available(self):
                return False
            def rank_output_lines(self, lines):
                return [0.0] * len(lines)
        lines = ["ERROR: bad"]
        scores = rank_lines(lines, graph_ctx=FakeCtx())
        # Should use keyword-only scores (graph unavailable)
        assert scores[0] > 0
