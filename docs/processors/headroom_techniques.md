# Headroom Compression Techniques

Token-saver ports several deterministic compression techniques from the
[headroom](https://github.com/nicholishen/headroom) conversation proxy. These
techniques add zero LLM calls and run as part of the existing post-tool hook
compression pipeline.

## Overview

The headroom techniques are organized into shared signal utilities under
`src/processors/_signals/`. These utilities are imported explicitly by
processors that need them — they are not auto-discovered as processors
themselves.

## Implemented Techniques

### 1. Error Detection (`_signals/error_detection.py`)

Centralized keyword detection transcribed from headroom's Rust
`keyword_detector.rs`. Provides:

- **Keyword sets**: `ERROR_KEYWORDS` (13), `WARNING_KEYWORDS` (2),
  `IMPORTANCE_KEYWORDS` (8), `SECURITY_KEYWORDS` (4), `ERROR_INDICATOR_KEYWORDS` (7)
- **Zero-result scrubbing**: Removes "no errors found" type messages to
  prevent false positives
- **Strong error indicators**: `content_has_strong_error_indicators()` requires
  2+ distinct error keywords after scrubbing
- **Line scoring**: `score_line()` returns `(category, score)` with weights
  from headroom: ERROR=1.0, SECURITY=0.85, WARNING=0.5, IMPORTANCE=0.3
- **Line ranking**: `rank_lines()` combines keyword scores (0.6 weight) with
  optional graph scores (0.4 weight)

### 2. Entropy Detection (`_signals/entropy.py`)

Identifies high-entropy content (tokens, secrets, hashes) that should be
preserved during compression. Uses normalized Shannon entropy via
`math.log2` + `Counter`.

- `SECRET_ENTROPY_MIN_LENGTH = 20`: Minimum span length
- `DEFAULT_ENTROPY_THRESHOLD = 0.85`: Entropy threshold
- `EntropyScore`: Computes and caches entropy for text
- `entropy_spans()`: Returns `(start, end)` char spans of high-entropy content
- `sticky_line_indices()`: Returns indices of lines containing high-entropy
  content — these are preserved during truncation

### 3. Adaptive Sizing (`_signals/adaptive_sizer.py`)

Replaces hardcoded `[:N]` list caps with the Kneedle algorithm. Uses bigram
frequency analysis, simhash clustering, and zlib validation to find optimal
item counts.

- `compute_keep_count(items, profile)`: Maps profile to bias
  (conservative=1.5, moderate=1.0, aggressive=0.7) and delegates to
  `compute_optimal_k`
- `compute_optimal_k()`: Combines bigram Kneedle with simhash clustering
- `_simhash()`: Uses `hashlib.md5(..., usedforsecurity=False)` (S324 auto-suppressed)

### 4. JSON Mask (`_signals/json_mask.py`)

Structure-preserving JSON compression with hand-rolled tokenization. Handles
truncated/partial JSON gracefully (unlike `json.loads`).

- `_tokenize_json()`: State machine tokenizer for partial JSON
- `_should_preserve_token()`: Rules for token preservation based on depth,
  importance, and array position
- `compress_json_string()`: Full compression pipeline

### 5. Cross-Turn Dedup (`_signals/cross_turn.py`)

Block-level deduplication across conversation turns. When the same content
appears in multiple turns, earlier occurrences are replaced with pointers.

- **Pointer format**: `[↑{N}L same as msg {ref_turn}: {anchor}]` (load-bearing)
- **Prefix monotonicity**: Only the last block is modified; earlier blocks
  are unchanged
- **Corpus persistence**: Stored in SQLite `dedup_corpus` table, not memory
- **Fuzzy dedup**: Optional MinHash-based similarity matching via graphify

### 6. Graphify Context (`_signals/graphify_context.py`)

Lazy, fail-open integration with the graphify knowledge graph.

- `detect_graph()`: Walks up from project root looking for
  `graphify-out/graph.json`
- `GraphContext`: Lazy-loading graph context with thread safety
- `file_importance()`: Degree centrality normalized by max degree
- `rank_output_lines()`: Ranks lines by graph importance (0.5s budget)

## Integration Points

### Generic Processor Pipeline

The generic processor pipeline (`src/processors/generic.py`) now includes:

1. ANSI strip
2. Progress bar strip
3. Blank line collapse
4. Repeated line collapse
5. Similar line collapse (numeric)
6. **Similar trailing collapse** (new — headroom `_dedupe_similar`)
7. **Stack trace collapse** (new — with fixed blank-line behavior)
8. Trailing whitespace strip
9. **Entropy-aware truncation** (new — sticky lines preserved)

### JSON Compression

`compress_json_value()` in `src/processors/utils.py` now uses:
- Adaptive sizing for list item counts (aggressive profile)
- Entropy detection for string preservation (high-entropy strings preserved)

### Core Compression

`src/core.py::compress()` now:
- Auto-detects graphify graph context
- Passes `graph_ctx` to the engine and processors
- Applies cross-turn dedup after engine compression (fail-open)
- Records cross-turn savings in the `savings` table

## Configuration

- `cross_turn_dedup` (default `True`): Enable/disable cross-turn dedup
- All headroom defaults are preserved (entropy 0.85, min K=3, etc.)

## Testing

Tests for the new signal utilities are in:
- `tests/test_signals_error.py`
- `tests/test_signals_entropy.py`
- `tests/test_signals_sizer.py`
- `tests/test_signals_cross_turn.py`
- `tests/test_json_mask.py`
