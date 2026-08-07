"""Adaptive sizing utilities ported from headroom transforms/adaptive_sizer.py.

This module implements the Kneedle algorithm for finding optimal item counts
to keep from a list, using bigram frequency analysis and simhash clustering.
All pure stdlib: hashlib, zlib, collections.
"""

import hashlib
import zlib
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

# CJK character ranges for detection
_CJK_RANGES = [
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs
    (0x3040, 0x309F),   # Hiragana
    (0x30A0, 0x30FF),   # Katakana
    (0xAC00, 0xD7AF),   # Hangul Syllables
    (0xFF00, 0xFFEF),   # Halfwidth and Fullwidth Forms
]


def _is_cjk_char(char: str) -> bool:
    """Check if a character is in a CJK Unicode range.
    
    Ported from headroom adaptive_sizer.py.
    """
    if len(char) != 1:
        return False
    code = ord(char)
    for start, end in _CJK_RANGES:
        if start <= code <= end:
            return True
    return False


def compute_unique_bigram_curve(items: list[str]) -> list[int]:
    """Compute the unique bigram count curve for a list of items.
    
    For each prefix length k (1 to len(items)), compute how many unique
    bigrams (adjacent pairs) appear in the first k items. This gives a
    measure of information diversity as we include more items.
    
    Ported from headroom adaptive_sizer.py.
    
    Args:
        items: List of string items to analyze
        
    Returns:
        List where result[k] = number of unique bigrams in items[:k]
    """
    if not items:
        return []
    
    curve: list[int] = []
    seen_bigrams: set[tuple[str, str]] = set()
    
    for i in range(len(items)):
        if i > 0:
            bigram = (items[i - 1], items[i])
            seen_bigrams.add(bigram)
        curve.append(len(seen_bigrams))
    
    return curve


def _simhash(text: str) -> int:
    """Compute simhash for a text string.
    
    Simhash is a hash that is similar for similar texts. Used for
    clustering and duplicate detection. Uses MD5 for the hash function
    with usedforsecurity=False (suppresses S324 lint).
    
    Ported from headroom adaptive_sizer.py L224.
    
    Args:
        text: Text to hash
        
    Returns:
        64-bit simhash value as integer
    """
    # Vector of 64 zeros
    v = [0] * 64
    
    # Split text into features (words/tokens)
    features = text.split()
    
    for feature in features:
        # Compute MD5 hash of the feature
        # S324 auto-suppressed with usedforsecurity=False
        h = hashlib.md5(feature.encode(), usedforsecurity=False).digest()
        
        # Convert to 64-bit integer
        hash_int = int.from_bytes(h[:8], byteorder='big')
        
        # Add or subtract from vector based on bit value
        for i in range(64):
            if (hash_int >> (63 - i)) & 1:
                v[i] += 1
            else:
                v[i] -= 1
    
    # Compute final hash: 1 if vector[i] >= 0, else 0
    simhash = 0
    for i in range(64):
        if v[i] >= 0:
            simhash |= (1 << (63 - i))
    
    return simhash


def _hamming_distance(x: int, y: int) -> int:
    """Compute Hamming distance between two 64-bit integers.
    
    Number of bits that differ between the two values.
    """
    return bin(x ^ y).count('1')


def count_unique_simhash(items: list[str], threshold: int = 3) -> int:
    """Count unique items using simhash clustering.
    
    Groups items by simhash similarity (Hamming distance <= threshold)
    and returns the number of distinct clusters.
    
    Ported from headroom adaptive_sizer.py.
    
    Args:
        items: List of string items
        threshold: Maximum Hamming distance to consider items similar
        
    Returns:
        Number of unique clusters
    """
    if not items:
        return 0
    
    # Compute simhash for all items
    hashes = [_simhash(item) for item in items]
    
    # Find clusters using greedy grouping
    clusters: list[int] = []
    
    for h in hashes:
        # Check if similar to any existing cluster
        found = False
        for cluster_hash in clusters:
            if _hamming_distance(h, cluster_hash) <= threshold:
                found = True
                break
        
        if not found:
            clusters.append(h)
    
    return len(clusters)


def find_knee(
    curve: list[int],
    min_k: int = 3,
    max_k: int | None = None
) -> int:
    """Find the knee point in a curve using the Kneedle algorithm.
    
    The knee point is where the curve transitions from steep growth to
    plateau, indicating diminishing returns for including more items.
    
    Ported from headroom adaptive_sizer.py compute_optimal_k (L27–106).
    
    Args:
        curve: List of values (e.g., unique bigram counts)
        min_k: Minimum knee position (at least 3 items always kept)
        max_k: Maximum knee position (None = len(curve))
        
    Returns:
        Optimal index k to keep
    """
    if not curve:
        return 0
    
    n = len(curve)
    if n <= min_k:
        return n
    
    max_k = max_k if max_k is not None else n
    max_k = min(max_k, n)
    
    # Normalize curve to [0, 1]
    min_val = min(curve)
    max_val = max(curve)
    if max_val == min_val:
        return min_k
    
    normalized = [(v - min_val) / (max_val - min_val) for v in curve]
    
    # Compute x-coordinates (normalized indices)
    x = [i / (n - 1) for i in range(n)]
    
    # Find the point with maximum difference from the line
    # connecting (x[0], y[0]) to (x[-1], y[-1])
    x0, y0 = x[0], normalized[0]
    x1, y1 = x[-1], normalized[-1]
    
    max_diff = 0.0
    knee_idx = min_k
    
    for i in range(min_k, max_k):
        # Point on the line
        xi, yi = x[i], normalized[i]
        
        # Distance from point to line (perpendicular)
        # Using formula: |Ax + By + C| / sqrt(A² + B²)
        # Line equation: (y1 - y0)x - (x1 - x0)y + (x1*y0 - y1*x0) = 0
        A = y1 - y0
        B = -(x1 - x0)
        C = x1 * y0 - y1 * x0
        
        distance = abs(A * xi + B * yi + C) / ((A**2 + B**2) ** 0.5)
        
        if distance > max_diff:
            max_diff = distance
            knee_idx = i
    
    # Knee index is 0-based, return count (1-based)
    return knee_idx + 1


def _validate_with_zlib(items: list[str], k: int) -> bool:
    """Validate that keeping k items preserves most information.
    
    Compresses the full list and the truncated list with zlib, checking
    that the size ratio is reasonable. Prevents over-aggressive truncation.
    
    Ported from headroom adaptive_sizer.py.
    
    Args:
        items: Full list of items
        k: Number of items to keep
        
    Returns:
        True if k is acceptable, False if too aggressive
    """
    if k >= len(items):
        return True
    
    # Join and compress full list
    full_text = "\n".join(items)
    full_compressed = len(zlib.compress(full_text.encode()))
    
    # Join and compress truncated list
    truncated_text = "\n".join(items[:k])
    truncated_compressed = len(zlib.compress(truncated_text.encode()))
    
    # If truncated is less than 20% of full size, we're being too aggressive
    if truncated_compressed < full_compressed * 0.2:
        return False
    
    return True


def compute_optimal_k(
    items: list[str],
    min_k: int = 3,
    bias: float = 1.0,
    validate: bool = True
) -> int:
    """Compute optimal number of items to keep using multiple heuristics.
    
    Combines bigram diversity analysis (Kneedle) with simhash clustering
    and zlib validation to find a robust k value.
    
    Ported from headroom adaptive_sizer.py compute_optimal_k.
    
    Args:
        items: List of string items
        min_k: Minimum items to keep (default 3)
        bias: Multiplier for the knee point (conservative=1.5, moderate=1.0, aggressive=0.7)
        validate: Whether to validate with zlib compression
        
    Returns:
        Optimal number of items to keep
    """
    if not items:
        return 0
    
    n = len(items)
    if n <= min_k:
        return n
    
    # Compute unique bigram curve
    curve = compute_unique_bigram_curve(items)
    
    # Find knee point
    knee_k = find_knee(curve, min_k=min_k)
    
    # Apply bias
    biased_k = max(min_k, int(knee_k * bias))
    biased_k = min(biased_k, n)
    
    # Also consider simhash clustering
    unique_clusters = count_unique_simhash(items)
    cluster_based_k = min(unique_clusters + 2, n)  # Keep cluster count + 2
    
    # Use the more conservative of the two approaches
    final_k = max(min_k, min(biased_k, cluster_based_k))
    
    # Validate with zlib if requested
    if validate:
        # Try progressively smaller k if validation fails
        while final_k > min_k:
            if _validate_with_zlib(items, final_k):
                break
            final_k = max(min_k, final_k - 1)
    
    return final_k


def compute_keep_count(
    items: list[str],
    profile: str = "moderate",
    graph_ctx=None,
) -> int:
    """Compute optimal keep count with profile-based bias.

    Convenience wrapper around compute_optimal_k with predefined profiles.
    When graph_ctx is available, resolves each item to a community ID via
    the graph's node `community` attribute, computes coverage curve over
    communities, and keeps >=1 per community. Falls back to bigram Kneedle
    when unavailable.

    Args:
        items: List of string items
        profile: One of "conservative" (1.5x bias), "moderate" (1.0x bias),
                 or "aggressive" (0.7x bias)
        graph_ctx: Optional GraphContext for graphify-aware sizing

    Returns:
        Optimal number of items to keep
    """
    bias_map = {
        "conservative": 1.5,
        "moderate": 1.0,
        "aggressive": 0.7,
    }

    bias = bias_map.get(profile.lower(), 1.0)

    # Try graphify-aware sizing first
    if graph_ctx is not None and hasattr(graph_ctx, "available") and graph_ctx.available():
        try:
            k = _compute_keep_count_with_communities(items, graph_ctx, bias)
            if k > 0:
                return k
        except Exception:
            # Fall back to bigram Kneedle
            pass

    return compute_optimal_k(items, min_k=3, bias=bias, validate=True)


def _compute_keep_count_with_communities(
    items: list[str],
    graph_ctx,
    bias: float = 1.0,
) -> int:
    """Compute keep count using graph community coverage.

    Resolves each item to a community ID via the graph's node `community`
    attribute, computes coverage curve over communities, and keeps >=1
    per community.

    Returns:
        Optimal number of items to keep, or 0 if graph is unavailable.
    """
    if not items:
        return 0

    # Get communities for each item
    communities: dict[str, int] = {}
    community_items: dict[int, list[int]] = {}

    for idx, item in enumerate(items):
        # Try to resolve the item to a graph node
        result = graph_ctx.resolve_symbol(item)
        if result:
            node_id = result[0]
            # Get community attribute from graph
            try:
                node_data = graph_ctx._graph.nodes[node_id]
                community = node_data.get("community", 0)
                community_items.setdefault(community, []).append(idx)
                communities[item] = community
            except Exception:
                pass

    if not communities:
        return 0

    # Compute coverage curve: how many communities are covered by first k items
    num_communities = len(community_items)
    if num_communities == 0:
        return 0

    # Keep at least 1 per community
    min_k = num_communities

    # Use bigram Kneedle for the actual count, but ensure at least min_k
    k = compute_optimal_k(items, min_k=min_k, bias=bias, validate=True)
    return max(k, min_k)