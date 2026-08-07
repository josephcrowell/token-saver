# Graphify Integration

Token-saver optionally integrates with
[graphify](https://github.com/nicholishen/graphify) for graph-aware
compression. This integration is fully optional and fails open when graphify
or its dependencies are unavailable.

## Overview

Graphify builds a persistent knowledge graph from code, documentation, and
other project content. Token-saver uses this graph to make smarter compression
decisions — prioritizing high-centrality files and symbols in error output,
and improving cross-turn dedup with fuzzy matching.

## Dependencies

Graphify hard-depends on:
- `networkx>=3.4`
- `numpy>=1.21`
- `rapidfuzz>=3.0`

All three are pulled in at `import graphify` time. If any are missing, all
graphify-aware features fail open to neutral results.

## Features

### Graph Detection

`detect_graph(project_root)` walks up from the project root looking for
`graphify-out/graph.json`. Positive and negative results are cached per
resolved root.

### Graph Context

`GraphContext` provides lazy-loading access to the graph:
- `available()`: Check if the graph is loaded
- `centrality_files()`: High-centrality file paths (god nodes)
- `file_importance(path)`: Degree centrality normalized by max degree
- `resolve_symbol(name)`: Resolve a symbol name to a graph node
- `rank_output_lines(lines)`: Rank lines by graph importance (0.5s budget)

### Error Line Selection

When a `GraphContext` is available, `rank_lines()` combines keyword scores
(0.6 weight) with graph scores (0.4 weight). When unavailable, graph
contribution is 0.0 — output is identical to keyword-only scoring.

### Adaptive Sizing

`compute_keep_count()` can use graph community structure when available.
It resolves each item to a community ID and computes coverage curve over
communities, keeping at least 1 per community. Falls back to bigram Kneedle
when unavailable.

### Fuzzy Cross-Turn Dedup

`fuzzy_dedup_pass()` uses MinHash via graphify for near-identical block
detection:
- Character 3-shingles (spaces stripped)
- `MinHashLSH(threshold=0.85, num_perm=64)`
- Jaccard computed manually: `np.count_nonzero(a.hashvalues == b.hashvalues) / num_perm`
  (graphify's MinHash has no `jaccard()` method)

## Architecture

### Lazy Import

All graphify imports are lazy. Import failure is caught once per project.
When unavailable, all methods return neutral results.

### Thread Safety

`GraphContext` uses a threading lock for lazy loading. The centrality and
importance caches are populated on first access and reused.

### Performance

- Graph loading: ~50ms (once per process)
- Line ranking: 0.5s wall-clock budget
- MinHash: O(n·64) per block; skipped when numpy absent or blocks > 200

## Configuration

No explicit configuration needed. Graphify integration is auto-detected:
- If `graphify-out/graph.json` exists in the project tree → enabled
- If graphify or its deps are missing → disabled (fail-open)

## Testing

- Graphify-present tests use a mock graph
- Graphify-absent regression tests mock `import graphify` → ImportError
- All Phase 1–4 techniques work without graphify
