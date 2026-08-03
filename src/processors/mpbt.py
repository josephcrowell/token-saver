"""MPBT meta-build tool output processor.

MPBT (mpbt-builder) drives package builds and emits Go-style timestamped
log lines around embedded cmake/ninja/make output. Successful runs produce
mostly noise (package loading, env dumps, probe results, clone chatter);
failures need the MPBT error line, CMake/compiler errors, and the panic.
"""

import re

from .base import Processor
from .cpp_build import CppBuildProcessor

_TS_RE = re.compile(r"^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d+\s+")

_FAILURE_RE = re.compile(
    r"(?:BUILD ERR on|panic:|build failed|CMake Error|FAILED:|\berror:|"
    r"(?:Configure|Build|Install|Prepare) error:)",
    re.IGNORECASE,
)

# Lines that carry real signal and must survive compression.
_SIGNAL_RE = re.compile(
    r"(?:BUILD ERR on \[?|\] (?:Configure|Build|Install|Prepare) error:|"
    r"panic:|CMake Error|FAILED:|\berror:|undefined reference|"
    r"ninja: build stopped|collect2: error|ld returned)",
    re.IGNORECASE,
)


class MpbtProcessor(Processor):
    priority = 11
    hook_patterns = [
        r"^(?:\S*/)?mpbt-builder\b",
        r"^(?:\./)?build-all\b",
    ]

    @property
    def name(self) -> str:
        return "mpbt"

    def can_handle(self, command: str) -> bool:
        return bool(
            re.search(r"(?:^|[;&]\s*)(?:\S+/)?mpbt-builder\b", command)
            or re.search(r"(?:^|[;&]\s*)\.?(?:\S*/)?build-all\b", command)
        )

    @staticmethod
    def _strip_ts(line: str) -> str:
        return _TS_RE.sub("", line)

    @staticmethod
    def _pkg_name(line: str) -> str:
        m = re.match(r"^\[([^\]]+)\]", line.strip())
        return m.group(1) if m else ""

    def _has_failure(self, lines: list[str]) -> bool:
        return any(_FAILURE_RE.search(line) for line in lines)

    def process(self, command: str, output: str) -> str:
        if not output or not output.strip():
            return output
        lines = [self._strip_ts(line) for line in output.splitlines()]
        if self._has_failure(lines):
            return self._extract_failures(lines)
        return self._summarize_success(lines)

    def _extract_failures(self, lines: list[str]) -> str:
        # Delegate compiler/cmake/ninja error extraction to the C++ build
        # processor, then prepend MPBT-level failure context it cannot know.
        cpp = CppBuildProcessor()
        cpp_result = cpp._extract_failures(lines)

        mpbt_errors = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if re.match(r"^BUILD ERR on ", stripped):
                mpbt_errors.append(stripped)
            elif m := re.search(r"\] ((?:Configure|Build|Install|Prepare) error:.*)$", stripped):
                pkg = self._pkg_name(stripped)
                mpbt_errors.append(f"[{pkg}] {m.group(1)}" if pkg else stripped)
            elif stripped.startswith("panic:") or re.match(
                r"^(?:CMake Error|feature_summary\(\) Error)", stripped
            ):
                mpbt_errors.append(stripped)

        # Deduplicate while preserving order
        seen = set()
        unique_errors = []
        for e in mpbt_errors:
            if e not in seen:
                seen.add(e)
                unique_errors.append(e)

        # Drop goroutine stack frames and MPBT bookkeeping noise that the
        # delegated extractor's ±2 context window may pull in.
        noise = re.compile(
            r"^(?:goroutine \d+|github\.com/|main\.main\(\)|\S*\.go:\d+|"
            r"\[PROJECT\]|\[\S+\] EXEC:|creating tarball:|current rev is|"
            r"no gitspec|pkg-config probe result:|loading solution:|fetching sources)",
            re.IGNORECASE,
        )
        cpp_lines = [line for line in cpp_result.splitlines() if not noise.match(line.strip())]

        result = ["MPBT build failed."]
        result.extend(unique_errors[:20])
        if len(unique_errors) > 20:
            result.append(f"... ({len(unique_errors) - 20} more MPBT errors)")
        # Skip lines already covered by the MPBT-level error list
        already = set(unique_errors)
        extra = [line for line in cpp_lines if line.strip() and line.strip() not in already]
        if extra:
            result.append("")
            result.extend(extra[:60])
            if len(extra) > 60:
                result.append(f"... ({len(extra) - 60} more build error lines)")
        return "\n".join(result)

    def _summarize_success(self, lines: list[str]) -> str:
        finished: list[str] = []
        tarballs: list[str] = []
        probes = 0
        no_gitspec = 0
        warnings: list[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.endswith(" finished build"):
                pkg = self._pkg_name(stripped)
                if pkg:
                    finished.append(pkg)
            elif stripped.startswith("creating tarball:"):
                tarballs.append(stripped.split("creating tarball:", 1)[1].strip())
            elif "pkg-config probe result:" in stripped:
                probes += 1
            elif "no gitspec - nothing to clone here" in stripped:
                no_gitspec += 1
            elif re.search(r"\bwarning:", stripped, re.IGNORECASE):
                if len(warnings) < 5:
                    warnings.append(stripped)

        result = [f"MPBT build succeeded: {len(finished)} package(s) built."]
        if finished:
            result.append(f"  built: {', '.join(finished)}")
        if tarballs:
            result.append(f"  tarballs: {len(tarballs)}")
            for t in tarballs[:3]:
                result.append(f"    {t}")
            if len(tarballs) > 3:
                result.append(f"    ... ({len(tarballs) - 3} more)")
        noise = []
        if probes:
            noise.append(f"{probes} system probes")
        if no_gitspec:
            noise.append(f"{no_gitspec} system packages (no clone)")
        if noise:
            result.append(f"  ({', '.join(noise)})")
        if warnings:
            result.append(f"  {len(warnings)} compiler warning(s) shown:")
            result.extend(f"    {w}" for w in warnings)
        return "\n".join(result)
