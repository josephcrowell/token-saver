"""Measure and record Graphify query context reduction."""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

if __package__:
    from .tracker import SavingsTracker
else:  # run as a script by the Kilo plugin: python3 <root>/src/graphify_metrics.py
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src.tracker import SavingsTracker


def parse_query_command(command: str) -> tuple[str, str | None] | None:
    """Return ``(question, cd_dir)`` for a ``graphify query "<question>"`` command.

    Accepts a path-prefixed ``graphify`` binary and a leading ``cd <dir> &&``
    (``cd_dir`` is that directory, else None).  Returns None for any other
    command, including other graphify subcommands.
    """
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return None

    cd_dir = None
    segment: list[str] = []
    for token in [*tokens, "&&"]:
        if token not in ("&&", ";"):
            segment.append(token)
            continue
        if len(segment) == 2 and segment[0] == "cd":
            cd_dir = segment[1]
        elif (
            len(segment) >= 3
            and os.path.basename(segment[0]) == "graphify"
            and segment[1] == "query"
            and not segment[2].startswith("-")
        ):
            return segment[2], cd_dir
        segment = []
    return None


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
