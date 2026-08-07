"""Autotools processor: autoreconf, automake, autoconf, libtoolize, configure.

Autotools' `configure` and `automake --add-missing` scripts print hundreds of
"checking for..." lines, plus autoconf/automake trace markers. This processor
collapses those into a per-verb count and preserves warnings/errors.
"""

import re
from collections import Counter

from .base import Processor

# ── Output patterns ────────────────────────────────────────────────
# `-- checking for X... yes/no` style and `checking for X... yes` style
_CHECK_RE = re.compile(
    r"^(?:--\s+)?checking(?:\s+for)?\s+(?P<rest>.*?)\s*\.{3,}\s*"
    r"(?P<result>yes|no|cached)\s*$",
    re.IGNORECASE,
)
_TRACES = re.compile(
    r"^(?:configure|automake|autoreconf|autoconf|libtoolize):\s+"
    r"(?:[^:\n]+:\s+)?"
    r"(?:invoking|entering|leaving|loading|running|pre-processing|"
    r"creating|generating|adding|wiring|copying|backing up|moving|"
    r"processing|putting|tracing)\b",
    re.IGNORECASE,
)
_ERROR_RE = re.compile(
    r"(?i)\b(?:error:|configure: error|automake: error|libtoolize: error|"
    r"autoreconf: error|autoconf: error|FATAL|"
    r"cannot find|no such file|not found|"
    r"undefined reference|"
    r"WARNING: |warning: )"
)


class AutotoolsProcessor(Processor):
    priority = 18.5
    hook_patterns = [
        r"^(?:\S*/)?(?:autoreconf|automake|autoconf|libtoolize|configure(?:\.ac|\.in)?)\b",
    ]

    @property
    def name(self) -> str:
        return "autotools"

    def can_handle(self, command: str) -> bool:
        return bool(
            re.search(
                r"(?:^|[;&]\s*)(?:\S*/)?(?:autoreconf|automake|autoconf|libtoolize)\b",
                command,
            )
            or re.search(
                r"(?:^|[;&]\s*)\./?configure(?:\s|--|$)",
                command,
            )
        )

    def process(self, command: str, output: str) -> str:
        if not output or not output.strip() or "|" in command:
            return output

        lines = output.splitlines()
        results: Counter[str] = Counter()
        trace_count = 0
        keep: list[str] = []
        errors: list[str] = []
        warnings: list[str] = []
        not_found: list[str] = []
        result_summary: list[str] = []
        suppressed = 0
        in_error_block = False
        error_block: list[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if _TRACES.match(stripped):
                trace_count += 1
                continue
            m = _CHECK_RE.match(stripped)
            if m:
                rest = m.group("rest").strip()
                result = m.group("result").lower()
                results[result] += 1
                # Suppress "no" results that are routine trait checks rather
                # than missing dependencies.  `rest` is everything after the
                # leading "checking [for]" so anything that doesn't look like
                # a tool or feature check is a runtime trait.
                is_trait = bool(
                    re.match(
                        r"^(?:whether|how|if|the |a |an )",
                        rest,
                        re.IGNORECASE,
                    )
                    or "support" in rest.lower()
                    or "support" in stripped.lower().split("...", 1)[0]
                )
                is_missing = (
                    (result == "no" and not is_trait)
                    or "not found" in rest.lower()
                    or "missing" in rest.lower()
                )
                if is_missing:
                    not_found.append(stripped)
                suppressed += 1
                continue
            if stripped.lower().startswith("creating "):
                result_summary.append(stripped)
                continue
            if re.match(r"^configure: creating \.", stripped):
                result_summary.append(stripped)
                continue
            if _ERROR_RE.search(stripped):
                if "warning" in stripped.lower():
                    warnings.append(stripped)
                else:
                    in_error_block = True
                    error_block.append(line)
                continue
            if in_error_block:
                if re.match(r"^\s", line) or stripped.startswith(("See ", "Consider ")):
                    error_block.append(line)
                    continue
                if error_block:
                    errors.append("\n".join(error_block).strip())
                error_block = []
                in_error_block = False
            keep.append(stripped)

        if in_error_block and error_block:
            errors.append("\n".join(error_block).strip())

        if not (
            results or errors or warnings or not_found or result_summary or trace_count
        ):
            return output

        result: list[str] = []
        if results:
            result.append(
                "configure: " + ", ".join(f"{k}={n}" for k, n in results.most_common())
            )
        if trace_count:
            result.append(f"  {trace_count} tool traces suppressed")
        if not_found:
            result.append("Not found:")
            for line in not_found[:5]:
                result.append(f"  {line}")
            if len(not_found) > 5:
                result.append(f"  ... ({len(not_found) - 5} more)")
        if result_summary:
            for line in result_summary[:5]:
                result.append(line)
        if errors:
            result.append("Errors:")
            for block in errors[:5]:
                result.append(block)
                result.append("")
        if warnings:
            result.append("Warnings:")
            for line in warnings[:5]:
                result.append(f"  {line}")
        return "\n".join(result).rstrip()
