"""Graphify context for graphify-aware compression.

This module provides lazy, fail-open integration with the graphify knowledge
graph. All code uses lazy `import graphify`. Import failure (covering networkx,
numpy, rapidfuzz) is caught once per project. When unavailable, all methods
return neutral results.
"""

import logging
import os
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

_log = logging.getLogger(__name__)

# Cache for graph detection results per resolved root
_detect_cache: dict[Path, Path | None] = {}
_detect_lock = threading.Lock()


def detect_graph(project_root: Path | str | None = None) -> Path | None:
    """Detect a graphify graph for the given project root.

    Walks up from project_root looking for `graphify-out/graph.json`.
    Caches positive and negative results per resolved root.

    Args:
        project_root: Project root directory. If None, uses cwd.

    Returns:
        Path to graph.json if found, None otherwise.
    """
    if project_root is None:
        project_root = Path.cwd()
    else:
        project_root = Path(project_root).resolve()

    with _detect_lock:
        if project_root in _detect_cache:
            return _detect_cache[project_root]

    # Walk up looking for graphify-out/graph.json
    current = project_root
    found = None

    for _ in range(20):  # Limit depth to prevent infinite loops
        candidate = current / "graphify-out" / "graph.json"
        if candidate.exists():
            found = candidate
            break
        parent = current.parent
        if parent == current:
            break
        current = parent

    with _detect_lock:
        _detect_cache[project_root] = found

    return found


class GraphContext:
    """Lazy-loading graphify graph context.

    All methods fail open: if graphify or its dependencies are unavailable,
    or the graph is corrupt/missing, methods return neutral results.
    """

    def __init__(self, graph_path: Path | str):
        """Initialize with a path to the graph.

        Args:
            graph_path: Path to graphify graph.json file
        """
        self._graph_path = Path(graph_path)
        self._available = False
        self._graph = None
        self._lock = threading.Lock()
        self._centrality_cache: frozenset[str] | None = None
        self._importance_cache: dict[str, float] = {}
        self._tried_load = False

    def _ensure_loaded(self) -> None:
        """Lazily load the graph if not already loaded.

        Under lock, imports graphify.affected.load_graph and calls it.
        Catches RuntimeError (graphify's corrupt/missing signal), SystemExit,
        ImportError, and broad Exception. On any failure: log DEBUG, set
        _available = False permanently.
        """
        if self._tried_load:
            return

        with self._lock:
            if self._tried_load:
                return
            self._tried_load = True

            try:
                from graphify.affected import load_graph  # noqa: PLC0415

                self._graph = load_graph(self._graph_path)
                self._available = True
                _log.debug("Loaded graphify graph from %s", self._graph_path)
            except RuntimeError:
                _log.debug("Graphify graph corrupt or missing: %s", self._graph_path)
                self._available = False
            except SystemExit:
                _log.debug("Graphify exited during load: %s", self._graph_path)
                self._available = False
            except ImportError:
                _log.debug("Graphify not available (import error)")
                self._available = False
            except Exception:
                _log.debug("Failed to load graphify graph", exc_info=True)
                self._available = False

    def available(self) -> bool:
        """Check if the graph is available for queries."""
        if not self._tried_load:
            self._ensure_loaded()
        return self._available

    def centrality_files(self) -> frozenset[str]:
        """Return a frozenset of high-centrality file paths.

        Calls graphify.analyze.god_nodes(self._graph), extracts source_file
        from node data. Caches in self._centrality_cache.

        Returns:
            Frozenset of file path strings, empty if unavailable.
        """
        if not self.available():
            return frozenset()

        if self._centrality_cache is not None:
            return self._centrality_cache

        try:
            from graphify.analyze import god_nodes  # noqa: PLC0415

            nodes = god_nodes(self._graph, top_n=10)
            files = set()
            for node in nodes:
                # Extract source_file from node data
                source_file = node.get("source_file") or node.get("id")
                if source_file and isinstance(source_file, str):
                    files.add(source_file)
            self._centrality_cache = frozenset(files)
        except Exception:
            _log.debug("Failed to get centrality files", exc_info=True)
            self._centrality_cache = frozenset()

        return self._centrality_cache

    def file_importance(self, path: str) -> float:
        """Get importance score for a file path.

        Degree centrality normalized by max degree.
        Uses manual memoization (cannot use lru_cache on a method).

        Args:
            path: File path to check

        Returns:
            Importance score between 0.0 and 1.0. Returns 0.5 when unavailable.
        """
        if not self.available():
            return 0.5

        if path in self._importance_cache:
            return self._importance_cache[path]

        importance = 0.5  # Default neutral

        try:
            # Check if this file is in the centrality set
            central_files = self.centrality_files()
            if path in central_files:
                importance = 1.0
            else:
                # Try to find the node in the graph and get its degree
                for node_id, node_data in self._graph.nodes(data=True):
                    if node_id == path or (
                        isinstance(node_data.get("source_file"), str)
                        and node_data["source_file"] == path
                    ):
                        degree = self._graph.degree(node_id)
                        max_degree = max(dict(self._graph.degree()).values()) if self._graph.number_of_nodes() > 0 else 1
                        importance = degree / max_degree if max_degree > 0 else 0.5
                        break
        except Exception:
            _log.debug("Failed to get file importance for %s", path, exc_info=True)
            importance = 0.5

        self._importance_cache[path] = importance
        return importance

    def resolve_symbol(self, name: str) -> tuple[str, float] | None:
        """Resolve a symbol name to a graph node.

        Calls graphify.affected.resolve_seed(self._graph, name).

        Args:
            name: Symbol name to resolve

        Returns:
            (node_id, importance) tuple or None if not found.
        """
        if not self.available():
            return None

        try:
            from graphify.affected import resolve_seed  # noqa: PLC0415

            result = resolve_seed(self._graph, name)
            if result:
                node_id = result if isinstance(result, str) else result.get("id")
                if node_id:
                    importance = self.file_importance(str(node_id))
                    return (str(node_id), importance)
        except Exception:
            _log.debug("Failed to resolve symbol %s", name, exc_info=True)

        return None

    def rank_output_lines(self, lines: list[str]) -> list[float]:
        """Rank lines by graph importance.

        Scans each line for file paths and identifiers, resolves via
        file_importance/resolve_symbol, returns max importance per line.
        0.5s wall-clock budget via time.monotonic().

        Args:
            lines: Lines to rank

        Returns:
            List of importance scores (0.0–1.0), one per line.
        """
        if not self.available():
            return [0.5] * len(lines)

        import re

        # Pattern to match file paths
        path_pattern = re.compile(r"[\w/.\-]+\.\w+")
        # Pattern to match identifiers (camelCase, snake_case)
        ident_pattern = re.compile(r"\b[a-zA-Z_][a-zA-Z0-9_]{3,}\b")

        scores = []
        start_time = time.monotonic()
        budget = 0.5  # 500ms

        for line in lines:
            if time.monotonic() - start_time > budget:
                # Budget exceeded — fill remaining with neutral
                scores.extend([0.5] * (len(lines) - len(scores)))
                break

            max_importance = 0.5

            # Check for file paths
            for match in path_pattern.finditer(line):
                path = match.group()
                importance = self.file_importance(path)
                max_importance = max(max_importance, importance)

            # Check for identifiers
            if max_importance <= 0.5:
                for match in ident_pattern.finditer(line):
                    name = match.group()
                    result = self.resolve_symbol(name)
                    if result:
                        max_importance = max(max_importance, result[1])

            scores.append(max_importance)

        return scores


def create_graph_context(project_root: Path | str | None = None) -> GraphContext | None:
    """Create a GraphContext if a graph is detected, None otherwise.

    Convenience function that detects the graph and creates a context.

    Args:
        project_root: Project root directory. If None, uses cwd.

    Returns:
        GraphContext if graph found, None otherwise.
    """
    graph_path = detect_graph(project_root)
    if graph_path is None:
        return None

    ctx = GraphContext(graph_path)
    if not ctx.available():
        return None

    return ctx