"""Measure and record Graphify query context reduction."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from .tracker import SavingsTracker


def corpus_tokens_from_report(project: str | Path) -> int | None:
    """Read Graphify's corpus word count and convert it to its naive token baseline."""
    report = Path(project) / "graphify-out" / "GRAPH_REPORT.md"
    try:
        text = report.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"-\s+([\d,]+) files\s+·\s+~([\d,]+) words", text)
    if not match:
        return None
    words = int(match.group(2).replace(",", ""))
    return words * 100 // 75


def query_tokens_from_output(output: str) -> int:
    """Estimate tokens in Graphify's returned traversal using its 4 chars/token rule."""
    return max(1, len(output) // 4) if output else 0


def record_query(
    project: str | Path,
    question: str,
    output: str,
    session_id: str | None = None,
) -> dict:
    """Record and return one Graphify query reduction measurement."""
    baseline = corpus_tokens_from_report(project)
    query_tokens = query_tokens_from_output(output)
    if not baseline or not query_tokens or query_tokens >= baseline:
        return {"recorded": False}
    tracker = SavingsTracker(session_id=session_id)
    try:
        recorded = tracker.record_graphify_saving(
            project=str(Path(project).resolve()),
            question=question,
            corpus_tokens=baseline,
            query_tokens=query_tokens,
        )
    finally:
        tracker.close()
    return {
        "recorded": recorded,
        "baseline_tokens": baseline,
        "query_tokens": query_tokens,
        "saved_tokens": baseline - query_tokens,
    }


def main() -> None:
    """Read a JSON event from stdin and write its measurement as JSON."""
    try:
        data = json.load(sys.stdin)
        result = record_query(
            project=data["project"],
            question=data["question"],
            output=data["output"],
            session_id=data.get("session_id"),
        )
    except Exception:
        result = {"recorded": False}
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
