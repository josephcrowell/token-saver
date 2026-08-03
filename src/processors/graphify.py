"""Graphify output processor for `graphify update` / `graphify watch`.

Progress output is dominated by per-batch AST extraction lines and repeated
tree-sitter-missing warnings. Compresses to: target, totals, rebuild stats,
and grouped warnings. Query results are left untouched.
"""

import re

from .base import Processor

_PROGRESS_RE = re.compile(r"^\s*AST extraction: \d+/\d+ uncached files")
_TREESITTER_RE = re.compile(
    r"^\s*warning: (\d+) (\.\w+|) file\(s\) contributed nothing to the graph "
    r"because a dependency is missing: (\S+) not installed"
)
_KEEP_RE = re.compile(
    r"^\[graphify(?: watch)?\] (?:Rebuilt|backed up|WARNING)|"
    r"^Code graph updated|^Nothing to update|^Re-extracting code files in|"
    r"^Tip:|^For doc"
)


class GraphifyProcessor(Processor):
    priority = 52
    hook_patterns = [
        r"^graphify\s+(?:update|watch|rebuild)\b",
        r"^GRAPHIFY_\w+=\S+\s+graphify\s+(?:update|watch|rebuild)\b",
    ]

    @property
    def name(self) -> str:
        return "graphify"

    def can_handle(self, command: str) -> bool:
        return bool(
            re.search(
                r"(?:^|[;&]\s*)(?:GRAPHIFY_\w+=\S+\s+)*graphify\s+"
                r"(?:update|watch|rebuild)\b",
                command,
            )
        )

    def process(self, command: str, output: str) -> str:
        if not output or not output.strip():
            return output

        kept: list[str] = []
        ts_warnings: dict[str, int] = {}
        progress_last: str | None = None
        other_warnings: list[str] = []

        for line in output.splitlines():
            stripped = line.strip()
            if not stripped:
                continue

            if _PROGRESS_RE.match(line):
                progress_last = stripped
                continue

            m = _TREESITTER_RE.match(line)
            if m:
                parser = m.group(3)
                ts_warnings[parser] = ts_warnings.get(parser, 0) + int(m.group(1))
                continue

            if _KEEP_RE.search(line):
                kept.append(stripped)
                continue

            if stripped.startswith("warning:"):
                other_warnings.append(stripped)
                continue

            # Structural lines (communities, backup paths, stats)
            if re.match(r"^(?:\[\S+\]|\S+ graph\.|community set|graph\.json)", stripped):
                kept.append(stripped)

        result: list[str] = []
        # First line is normally the "Re-extracting" header — keep it first.
        headers = [k for k in kept if k.startswith("Re-extracting")]
        rest = [k for k in kept if not k.startswith("Re-extracting")]
        result.extend(headers[:1])

        if progress_last:
            result.append(f"  {progress_last} (progress lines collapsed)")

        if ts_warnings:
            total = sum(ts_warnings.values())
            parsers = ", ".join(
                f"{p}x{n}" for p, n in sorted(ts_warnings.items(), key=lambda kv: -kv[1])
            )
            result.append(f"  tree-sitter missing: {total} file(s) skipped [{parsers}]")

        result.extend(rest)

        if other_warnings:
            result.append(f"  {len(other_warnings)} other warning(s):")
            result.extend(f"    {w}" for w in other_warnings[:5])
            if len(other_warnings) > 5:
                result.append(f"    ... ({len(other_warnings) - 5} more)")

        return "\n".join(result) if result else output
