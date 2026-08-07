"""Cross-turn verbatim dedup ported from headroom transforms/cross_turn_dedup.py.

This module provides block-level deduplication across conversation turns.
When the same content appears in multiple turns (e.g. re-running the same
command), earlier occurrences are replaced with pointers to the first
occurrence, reducing repetition in the conversation context.

All pure stdlib, deterministic, fail-open. The corpus is persisted in SQLite
via SavingsTracker, not in process memory.
"""

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

# Constants from headroom cross_turn_dedup.py
DEFAULT_MIN_LINES = 3
DEFAULT_MIN_CHARS = 40
MAX_ANCHOR_CANDIDATES = 16

# Line number pattern for normalization
_LINENO_RE = re.compile(r":\d+:")


@dataclass
class DedupBlock:
    """A single block of text for cross-turn dedup.
    
    Attributes:
        text: The text content of the block
        turn: 1-based turn number (absolute ordinal)
    """
    text: str
    turn: int


@dataclass
class DedupStats:
    """Statistics from a dedup run."""
    spans_folded: int = 0
    chars_saved: int = 0
    exact_folds: int = 0
    fuzzy_folded: int = 0


def _num_and_key(line: str) -> tuple[str, str]:
    """Extract line number and key from a line.
    
    Normalizes line numbers for comparison so that
    "file.py:10: error" and "file.py:20: error" match the same key.
    
    Returns:
        (normalized_number, key) tuple
    """
    # Replace line numbers with a placeholder
    normalized = _LINENO_RE.sub(":N:", line)
    # Split on the first N placeholder to get number and key
    if ":N:" in normalized:
        parts = normalized.split(":N:", 1)
        return parts[0], parts[1]
    return "", normalized


def _is_trivial(line: str) -> bool:
    """Check if a line is trivial (too short or whitespace-only).
    
    Trivial lines are not useful as anchors for dedup.
    """
    stripped = line.strip()
    return len(stripped) < 3


def _pointer(n_lines: int, ref_turn: int, anchor: str) -> str:
    """Generate a cross-turn dedup pointer.
    
    Format: [↑{N}L same as msg {ref_turn}: {anchor}]
    
    The `msg` label and `↑` arrow are load-bearing (from headroom _pointer L142-143).
    
    Args:
        n_lines: Number of lines folded
        ref_turn: The reference turn number (1-based absolute ordinal)
        anchor: First line of the folded content (for context)
        
    Returns:
        Pointer string in the canonical format
    """
    # Truncate anchor to reasonable length
    anchor = anchor.strip()[:80]
    return f"[↑{n_lines}L same as msg {ref_turn}: {anchor}]"


def _index_lines(text: str) -> list[str]:
    """Split text into lines for indexing."""
    return text.splitlines()


def _longest_match(
    candidate_lines: list[str],
    corpus_lines: list[str],
    min_lines: int = DEFAULT_MIN_LINES,
    min_chars: int = DEFAULT_MIN_CHARS,
) -> tuple[int, int] | None:
    """Find the longest matching span between candidate and corpus lines.
    
    Args:
        candidate_lines: Lines from the candidate block
        corpus_lines: Lines from the corpus block to compare against
        min_lines: Minimum number of matching lines required
        min_chars: Minimum total character count required
        
    Returns:
        (start, length) tuple of the match in candidate_lines, or None
    """
    if not candidate_lines or not corpus_lines:
        return None
    
    best_start = -1
    best_length = 0
    
    # Try each starting position in candidate
    for start in range(len(candidate_lines)):
        # Try each starting position in corpus
        for c_start in range(len(corpus_lines)):
            # Count matching lines from these positions
            length = 0
            total_chars = 0
            while (
                start + length < len(candidate_lines)
                and c_start + length < len(corpus_lines)
                and candidate_lines[start + length] == corpus_lines[c_start + length]
            ):
                total_chars += len(candidate_lines[start + length])
                length += 1
            
            # Check if this match is long enough
            if length >= min_lines and total_chars >= min_chars and length > best_length:
                best_start = start
                best_length = length
    
    if best_start >= 0 and best_length >= min_lines:
        return (best_start, best_length)
    return None


def dedup_blocks(
    blocks: list[DedupBlock],
    min_lines: int = DEFAULT_MIN_LINES,
    min_chars: int = DEFAULT_MIN_CHARS,
) -> tuple[list[DedupBlock], DedupStats]:
    """Deduplicate blocks against earlier blocks in the sequence.
    
    For each block, check if its content appears verbatim in any earlier
    block. If so, replace the matching span with a pointer.
    
    Due to prefix monotonicity, earlier blocks' outputs are identical to
    their inputs. Only the last block is actually modified.
    
    Args:
        blocks: List of DedupBlock objects in turn order
        min_lines: Minimum matching lines to fold
        min_chars: Minimum matching characters to fold
        
    Returns:
        (modified_blocks, stats) tuple. The modified_blocks list has the
        same length as input; only the last block may differ.
    """
    if not blocks:
        return [], DedupStats()
    
    if len(blocks) == 1:
        return blocks, DedupStats()
    
    stats = DedupStats()
    out_blocks = list(blocks)  # Copy, don't modify input
    
    # Only modify the last block
    last_block = blocks[-1]
    last_lines = _index_lines(last_block.text)
    
    # Build anchor candidates from earlier blocks
    # Look for matches in reverse order (most recent first)
    best_match: tuple[int, int, int] | None = None  # (ref_turn, start, length)
    
    for ref_block in reversed(blocks[:-1]):
        ref_lines = _index_lines(ref_block.text)
        
        # Limit anchor candidates for performance
        if len(ref_lines) > MAX_ANCHOR_CANDIDATES * 10:
            # Sample lines from the reference block
            step = len(ref_lines) // MAX_ANCHOR_CANDIDATES
            ref_sample = ref_lines[::step][:MAX_ANCHOR_CANDIDATES * 5]
        else:
            ref_sample = ref_lines
        
        match = _longest_match(last_lines, ref_sample, min_lines, min_chars)
        if match is not None:
            start, length = match
            if best_match is None or length > best_match[2]:
                best_match = (ref_block.turn, start, length)
    
    if best_match is not None:
        ref_turn, start, length = best_match
        
        # Build the folded text
        anchor = last_lines[start] if start < len(last_lines) else ""
        pointer = _pointer(length, ref_turn, anchor)
        
        # Replace the matching span with the pointer
        folded_lines = (
            last_lines[:start]
            + [pointer]
            + last_lines[start + length:]
        )
        
        folded_text = "\n".join(folded_lines)
        out_blocks[-1] = DedupBlock(text=folded_text, turn=last_block.turn)
        
        stats.spans_folded = 1
        stats.exact_folds = 1
        stats.chars_saved = len(last_block.text) - len(folded_text)
    
    return out_blocks, stats


def is_prefix_monotonic(blocks: list[DedupBlock]) -> bool:
    """Check if blocks are prefix-monotonic.
    
    A sequence is prefix-monotonic if each block's output is a prefix
    extension of the previous block's output. This property ensures that
    dedup only needs to modify the last block.
    
    Args:
        blocks: List of DedupBlock objects
        
    Returns:
        True if the blocks are prefix-monotonic
    """
    if len(blocks) <= 1:
        return True
    
    for i in range(1, len(blocks)):
        prev_lines = _index_lines(blocks[i - 1].text)
        curr_lines = _index_lines(blocks[i].text)
        
        # Check if previous lines are a prefix of current lines
        if len(prev_lines) > len(curr_lines):
            return False
        
        for j in range(len(prev_lines)):
            if prev_lines[j] != curr_lines[j]:
                return False
    
    return True


def fuzzy_dedup_pass(
    blocks: list[DedupBlock],
    threshold: float = 0.85,
    max_blocks: int = 200,
) -> tuple[list[DedupBlock], DedupStats]:
    """Fuzzy dedup pass using MinHash via graphify.
    
    Lazy imports graphify._minhash. On ImportError, returns blocks unchanged.
    
    Args:
        blocks: List of DedupBlock objects
        threshold: Jaccard similarity threshold for fuzzy match
        max_blocks: Maximum blocks to process (skip if more)
        
    Returns:
        (modified_blocks, stats) tuple
    """
    stats = DedupStats()
    
    if len(blocks) <= 1 or len(blocks) > max_blocks:
        return blocks, stats
    
    try:
        from graphify._minhash import MinHash, MinHashLSH
        import numpy as np
    except ImportError:
        # graphify or numpy not available — fail open
        return blocks, stats
    
    num_perm = 64
    
    # Compute MinHash for each block
    minhashes: list[tuple[int, MinHash]] = []
    lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
    
    for idx, block in enumerate(blocks[:-1]):
        # Create character 3-shingles, stripping spaces first
        text = block.text.replace(" ", "").replace("\t", "").replace("\n", "")
        if len(text) < 10:
            continue
        
        mh = MinHash(num_perm=num_perm)
        for i in range(len(text) - 2):
            shingle = text[i:i + 3].encode()
            mh.update(shingle)
        
        minhashes.append((idx, mh))
        lsh.insert(f"block_{idx}", mh)
    
    # Check the last block for fuzzy matches
    last_block = blocks[-1]
    last_text = last_block.text.replace(" ", "").replace("\t", "").replace("\n", "")
    
    if len(last_text) < 10:
        return blocks, stats
    
    last_mh = MinHash(num_perm=num_perm)
    for i in range(len(last_text) - 2):
        shingle = last_text[i:i + 3].encode()
        last_mh.update(shingle)
    
    # Query LSH for similar blocks
    candidates = lsh.query(last_mh)
    
    if not candidates:
        return blocks, stats
    
    # Find the best match by computing Jaccard manually
    best_jaccard = 0.0
    best_ref_turn = -1
    
    for candidate_key in candidates:
        # Find the block index
        for idx, mh in minhashes:
            if f"block_{idx}" == candidate_key:
                # Compute Jaccard manually: np.count_nonzero(a.hashvalues == b.hashvalues) / num_perm
                jaccard = np.count_nonzero(mh.hashvalues == last_mh.hashvalues) / num_perm
                if jaccard > best_jaccard:
                    best_jaccard = jaccard
                    best_ref_turn = blocks[idx].turn
                break
    
    # If we found a good match, replace with a fuzzy pointer
    if best_jaccard >= threshold and best_ref_turn >= 0:
        # Only fold if remaining content is substantial
        last_lines = _index_lines(last_block.text)
        if len(last_block.text) > 120:
            n_lines = len(last_lines)
            anchor = last_lines[0] if last_lines else ""
            pointer = f"[↑~{n_lines}L near-identical to msg {best_ref_turn}]"
            
            folded_block = DedupBlock(text=pointer, turn=last_block.turn)
            out_blocks = list(blocks)
            out_blocks[-1] = folded_block
            
            stats.fuzzy_folded = 1
            stats.chars_saved = len(last_block.text) - len(pointer)
            
            return out_blocks, stats
    
    return blocks, stats