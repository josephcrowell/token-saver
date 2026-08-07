"""Error detection utilities ported from headroom keyword_detector.rs.

This module provides centralized keyword sets and pattern matching for
detecting errors, warnings, and other important signals in command output.
"""

import logging
import re
from typing import TYPE_CHECKING

_log = logging.getLogger(__name__)

# Keyword sets transcribed verbatim from Rust keyword_detector.rs::KeywordRegistry::default_set()
# See: crates/headroom-core/src/signals/keyword_detector.rs L78–118

ERROR_KEYWORDS = frozenset({
    "error", "exception", "fail", "failed", "failure",
    "fatal", "critical", "crash", "panic", "abort",
    "timeout", "denied", "rejected",
})

WARNING_KEYWORDS = frozenset({"warn", "warning"})

IMPORTANCE_KEYWORDS = frozenset({
    "important", "note", "todo", "fixme", "hack", "xxx", "bug", "fix",
})

SECURITY_KEYWORDS = frozenset({"security", "auth", "password", "secret"})

ERROR_INDICATOR_KEYWORDS = (
    "error", "fail", "exception", "traceback", "fatal", "panic", "crash",
)

# Compiled patterns for efficient matching
ERROR_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in ERROR_KEYWORDS) + r")\b",
    re.IGNORECASE
)

WARNING_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in WARNING_KEYWORDS) + r")\b",
    re.IGNORECASE
)

IMPORTANCE_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in IMPORTANCE_KEYWORDS) + r")\b",
    re.IGNORECASE
)

SECURITY_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in SECURITY_KEYWORDS) + r")\b",
    re.IGNORECASE
)

# Zero-result scrubbing pattern from headroom error_detection.py L160–167
_ZERO_RESULT_PATTERN = re.compile(
    r"^\s*(no|zero|0|empty|none|not found|nothing|nothing to show)\s*"
    r"(results?|items?|files?|matches?|packages?|modules?|resources?|changes?|errors?|warnings?)\s*$",
    re.IGNORECASE
)

# Scoring weights from headroom log_compressor.py::_score_line (L323–339)
_SCORES = {
    "error": 1.0,
    "fail": 1.0,
    "security": 0.85,
    "warning": 0.5,
    "importance": 0.3,
}

# Additional pattern matches for scoring
_STACK_TRACE_PATTERN = re.compile(
    r"^\s*at\s+|^\s*File\s+\"[^\"]+\".*line\s+\d+|Traceback|^\s*from\s+"
)
_SUMMARY_PATTERN = re.compile(r"^\s*(summary|totals?|overall|final)\s*:", re.IGNORECASE)


def content_has_strong_error_indicators(text: str) -> bool:
    """Check if content has strong error indicators.

    Scrubs zero-result patterns first (to avoid false positives on
    "no errors found" messages), then checks for 2+ distinct error
    indicator keywords.

    Args:
        text: Content to check

    Returns:
        True if content has strong error indicators (≥2 distinct keywords)
    """
    # Scrub zero-result patterns first
    scrubbed = _ZERO_RESULT_PATTERN.sub(" ", text.lower())
    
    # Count distinct error indicator keyword matches
    found_keywords = set()
    for keyword in ERROR_INDICATOR_KEYWORDS:
        if keyword in scrubbed:
            found_keywords.add(keyword)
    
    return len(found_keywords) >= 2


def score_line(line: str, context: str = "text") -> tuple[str | None, float]:
    """Score a line for error/importance signals.

    Returns a (category, score) tuple or (None, 0.0) if no match.
    Scoring follows headroom's log_compressor.py::_score_line:
    - ERROR/FAIL: 1.0
    - SECURITY: 0.85
    - WARNING: 0.5
    - IMPORTANCE: 0.3
    - Stack trace: +0.3
    - Summary: +0.4
    - Capped at 1.0

    Args:
        line: Line to score
        context: Context type ("text", "log", "code") - affects scoring rules

    Returns:
        (category, score) tuple or (None, 0.0)
    """
    line_lower = line.lower()
    line_stripped = line.strip()
    
    score = 0.0
    category = None
    
    # Check patterns in priority order
    if ERROR_PATTERN.search(line_lower):
        score = _SCORES["error"]
        category = "error"
    elif SECURITY_PATTERN.search(line_lower):
        score = _SCORES["security"]
        category = "security"
    elif WARNING_PATTERN.search(line_lower):
        score = _SCORES["warning"]
        category = "warning"
    elif IMPORTANCE_PATTERN.search(line_lower):
        score = _SCORES["importance"]
        category = "importance"
    else:
        # No base category match
        return None, 0.0
    
    # Context-specific adjustments
    if context not in ("text", "log", "code"):
        _log.debug("Unknown context name %r, using 'text' context", context)
        context = "text"
    
    if context in ("text", "log"):
        # Stack trace bonus
        if _STACK_TRACE_PATTERN.search(line_stripped):
            score += 0.3
            if category is None:
                category = "stack_trace"
        
        # Summary bonus
        if _SUMMARY_PATTERN.search(line_stripped):
            score += 0.4
            if category is None:
                category = "summary"
    
    # Cap at 1.0
    score = min(score, 1.0)
    
    return category, score


def has_error_keywords(text: str) -> bool:
    """Quick check if text contains any error keywords."""
    return bool(ERROR_PATTERN.search(text))


def has_warning_keywords(text: str) -> bool:
    """Quick check if text contains any warning keywords."""
    return bool(WARNING_PATTERN.search(text))


def has_importance_keywords(text: str) -> bool:
    """Quick check if text contains any importance keywords."""
    return bool(IMPORTANCE_PATTERN.search(text))


def has_security_keywords(text: str) -> bool:
    """Quick check if text contains any security keywords."""
    return bool(SECURITY_PATTERN.search(text))


def scrub_zero_result_patterns(text: str) -> str:
    """Remove zero-result patterns from text.
    
    Used to prevent false positives on messages like "no errors found".
    """
    return _ZERO_RESULT_PATTERN.sub(" ", text)


def rank_lines(
    lines: list[str],
    graph_ctx=None,
    context: str = "text",
) -> list[float]:
    """Rank lines by combined keyword and graph importance scores.

    Combines keyword scores (0.6 weight) with graph scores (0.4 weight).
    When graph_ctx is None or unavailable, graph contribution is 0.0 —
    output is identical to keyword-only scoring.

    Args:
        lines: Lines to rank
        graph_ctx: Optional GraphContext for graphify-aware ranking
        context: Context type for score_line

    Returns:
        List of scores (0.0–1.0), one per line.
    """
    # Get keyword scores
    keyword_scores = [score_line(line, context)[1] for line in lines]

    # Get graph scores if available
    if graph_ctx is not None and hasattr(graph_ctx, "available") and graph_ctx.available():
        graph_scores = graph_ctx.rank_output_lines(lines)
    else:
        graph_scores = [0.0] * len(lines)

    # Combine with weights: 0.6 keyword + 0.4 graph
    combined = [
        0.6 * kw + 0.4 * gh
        for kw, gh in zip(keyword_scores, graph_scores, strict=False)
    ]

    return combined