"""Entropy-based detection utilities ported from headroom compression/masks.py.

This module provides functions for computing Shannon entropy and identifying
high-entropy spans that likely contain secrets, tokens, or other identifiers
that should be preserved during compression.
"""

import math
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

# Minimum length for a text span to be considered for entropy analysis
SECRET_ENTROPY_MIN_LENGTH = 20

# Default entropy threshold for considering content "high entropy"
DEFAULT_ENTROPY_THRESHOLD = 0.85


class EntropyScore:
    """Compute and cache entropy scores for text.
    
    Ported from headroom compression/masks.py::EntropyScore (L264–302).
    Uses normalized Shannon entropy via math.log2 + Counter.
    """

    def __init__(self, text: str, threshold: float = DEFAULT_ENTROPY_THRESHOLD):
        """Initialize entropy score computation.
        
        Args:
            text: Text to analyze
            threshold: Entropy threshold (0.0–1.0) for considering content high-entropy
        """
        self.text = text
        self.threshold = threshold
        self._entropy: float | None = None
        self._is_high_entropy: bool | None = None

    def compute(self, threshold: float | None = None) -> float:
        """Compute normalized Shannon entropy.
        
        Returns entropy in range [0.0, 1.0], where higher values indicate
        more randomness/unpredictability. Uses base-2 logarithm.
        
        Args:
            threshold: Optional override of the threshold from constructor
            
        Returns:
            Normalized entropy value between 0.0 and 1.0
        """
        if self._entropy is None:
            if not self.text:
                self._entropy = 0.0
                return 0.0

            # Count character frequencies
            counter = Counter(self.text)
            length = len(self.text)
            
            # Compute Shannon entropy: H = -sum(p_i * log2(p_i))
            entropy = 0.0
            for count in counter.values():
                if count > 0:
                    probability = count / length
                    entropy -= probability * math.log2(probability)
            
            # Normalize by max possible entropy (log2 of alphabet size)
            # For a completely random string, entropy approaches log2(alphabet_size)
            # We normalize to [0, 1] by dividing by log2(min(len(unique_chars), 256))
            # This gives a practical upper bound for typical ASCII/UTF-8 text
            max_entropy = math.log2(min(len(counter), 256))
            if max_entropy > 0:
                self._entropy = entropy / max_entropy
            else:
                self._entropy = 0.0

        return self._entropy

    @property
    def is_high_entropy(self) -> bool:
        """Check if entropy exceeds threshold."""
        if self._is_high_entropy is None:
            self._is_high_entropy = self.compute() >= self.threshold
        return self._is_high_entropy


def entropy_spans(
    content: str,
    threshold: float = DEFAULT_ENTROPY_THRESHOLD,
    min_length: int = SECRET_ENTROPY_MIN_LENGTH,
) -> list[tuple[int, int]]:
    """Find high-entropy character spans in content.
    
    Adapts headroom's compute_entropy_mask_for_content (L356–406) to return
    (start, end) character spans instead of a mask.
    
    Args:
        content: Text to analyze
        threshold: Entropy threshold (0.0–1.0)
        min_length: Minimum span length to consider
        
    Returns:
        List of (start, end) tuples representing high-entropy spans
    """
    if not content or len(content) < min_length:
        return []

    spans: list[tuple[int, int]] = []
    
    # Use a sliding window approach to find high-entropy regions
    # Start with the minimum length and expand
    window_size = min_length
    i = 0
    
    while i < len(content) - window_size + 1:
        # Check if window is high entropy
        window = content[i:i + window_size]
        scorer = EntropyScore(window, threshold)
        
        if scorer.is_high_entropy:
            # Expand window while entropy remains high
            start = i
            end = i + window_size
            
            while end < len(content):
                expanded = content[start:end + 1]
                if len(expanded) < min_length:
                    end += 1
                    continue
                    
                expanded_scorer = EntropyScore(expanded, threshold)
                if not expanded_scorer.is_high_entropy:
                    break
                end += 1
            
            spans.append((start, end))
            i = end  # Skip past this span
        else:
            i += 1
    
    return spans


def sticky_line_indices(
    lines: list[str],
    threshold: float = DEFAULT_ENTROPY_THRESHOLD,
    min_length: int = SECRET_ENTROPY_MIN_LENGTH,
) -> frozenset[int]:
    """Find indices of lines containing high-entropy content.
    
    A line is "sticky" if it contains at least one high-entropy word
    or span. Sticky lines should be preserved during truncation.
    
    Args:
        lines: List of lines to check
        threshold: Entropy threshold (0.0–1.0)
        min_length: Minimum span length to consider
        
    Returns:
        Frozenset of line indices that contain high-entropy content
    """
    sticky = set()
    
    for idx, line in enumerate(lines):
        # Skip very short lines
        if len(line) < min_length:
            continue
        
        # Check for high-entropy spans in the line
        spans = entropy_spans(line, threshold, min_length)
        if spans:
            sticky.add(idx)
            continue
        
        # Also check individual words (space-separated tokens)
        words = line.split()
        for word in words:
            if len(word) >= min_length:
                scorer = EntropyScore(word, threshold)
                if scorer.is_high_entropy:
                    sticky.add(idx)
                    break
    
    return frozenset(sticky)


def compute_entropy(text: str) -> float:
    """Compute normalized Shannon entropy for text.
    
    Convenience function that creates an EntropyScore and computes.
    
    Args:
        text: Text to analyze
        
    Returns:
        Normalized entropy between 0.0 and 1.0
    """
    return EntropyScore(text).compute()


def is_high_entropy(text: str, threshold: float = DEFAULT_ENTROPY_THRESHOLD) -> bool:
    """Check if text has high entropy.
    
    Convenience function that creates an EntropyScore and checks.
    
    Args:
        text: Text to analyze
        threshold: Entropy threshold
        
    Returns:
        True if entropy exceeds threshold
    """
    return EntropyScore(text, threshold).is_high_entropy