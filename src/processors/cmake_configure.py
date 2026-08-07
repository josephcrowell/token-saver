"""CMake configure processor for `cmake -B build -S .`, `cmake -DCMAKE_BUILD_TYPE=...`.

CMake's configuration phase prints a long banner of "looking for...",
"checking for...", "found..." messages, plus toolchain and feature reports.
The build phase (`cmake --build`) is handled by cpp_build.py; this processor
is for the configure phase only.
"""

import re
from collections import Counter

from .base import Processor

# ── Output patterns ────────────────────────────────────────────────
# Bash-style status lines from CMake's `message(STATUS ...)` helpers and
# find_package output.
_CHECK_RE = re.compile(
    r"^(?P<indent>\s*)--\s+(?P<verb>[A-Z][a-z]+(?:ing|ation)?)\s+(?P<rest>.*)$"
)
_TARGET_RE = re.compile(r"^\s*--\s+(?P<name>[\w./-]+)\s+[:=]\s+(?P<value>.+)$")
_NOT_FOUND_RE = re.compile(
    r"(?i)(?:\bnot found\b|not installed|could not find|missing)"
)
_ERROR_RE = re.compile(
    r"(?i)\b(?:CMake Error|Error in cmake code|FATAL Error|undefined reference|"
    r"command failed|not found|missing|"
    r"CMake Warning|Warning:)\b"
)
_FEATURE_RE = re.compile(
    r"^(?P<indent>\s*)--\s+The following (?:features|packages|REQUIRES|options) "
)


class CmakeConfigureProcessor(Processor):
    # Below cmake_install (12) and Flutter (11) so the configure phase is
    # recognized.  Above CppBuildProcessor (14) so plain `cmake -B build` does
    # not fall through to the build processor.
    priority = 11.5
    hook_patterns = [
        r"^(?:\S*/)?cmake\b(?!.*--build)(?!.*--install)(?!.*-E\s+install)",
    ]

    @property
    def name(self) -> str:
        return "cmake_configure"

    def can_handle(self, command: str) -> bool:
        if "cmake" not in command:
            return False
        # Skip build, install, and -E (script/CMake-mode) commands
        if re.search(r"cmake\s+--build\b", command):
            return False
        if re.search(r"cmake\s+--install\b", command):
            return False
        if re.search(r"cmake\s+-E\b", command):
            return False
        return bool(
            re.search(
                r"(?:^|[;&]\s*)(?:\S*/)?cmake\s+(?:-[A-Z]\S*\s+)*"
                r"(?:-(?:B|S|D|U)\s+\S+|--build|--install|"
                r"-DCMAKE_BUILD_TYPE=|-G\s+\S+|"
                r"-DCMAKE_(?:TOOLCHAIN|CXX_COMPILER|CC_COMPILER|C_COMPILER|PREFIX|INSTALL_PREFIX))",
                command,
            )
            or re.search(
                r"(?:^|[;&]\s*)(?:\S*/)?cmake\s+-(?:B|S|D|P)\s+",
                command,
            )
        )

    def process(self, command: str, output: str) -> str:
        if not output or not output.strip() or "|" in command:
            return output

        lines = output.splitlines()
        verb_counts: Counter[str] = Counter()
        keep: list[str] = []
        errors: list[str] = []
        warnings: list[str] = []
        not_found: list[str] = []
        target_lines: list[str] = []
        suppressed = 0
        in_error_block = False

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # Errors and warnings come first; CMake errors span multiple lines
            # and we want to keep the indented continuation.
            if re.search(r"CMake Error", stripped) or re.search(
                r"^Error in cmake code", stripped
            ):
                errors.append(line)
                in_error_block = True
                continue
            if in_error_block and (re.match(r"^\s", line) or stripped == ""):
                if stripped:
                    errors.append(line)
                continue
            if re.search(r"CMake Warning", stripped):
                warnings.append(line)
                in_error_block = False
                continue
            if re.search(r"(?i)\bFATAL Error\b", stripped) or stripped.startswith(
                "CMake Error"
            ):
                errors.append(line)
                in_error_block = True
                continue

            m = _CHECK_RE.match(line)
            if m:
                verb = m.group("verb").lower()
                rest = m.group("rest")
                # Track key verbs; suppress the routine ones
                if verb in (
                    "checking",
                    "looking",
                    "found",
                    "searching",
                    "loading",
                    "detecting",
                    "performing",
                    "initializing",
                ):
                    verb_counts[verb] += 1
                    if _NOT_FOUND_RE.search(rest):
                        not_found.append(line.strip())
                    suppressed += 1
                    continue
                if _NOT_FOUND_RE.search(rest) or _NOT_FOUND_RE.search(verb):
                    not_found.append(line.strip())
                    suppressed += 1
                    continue
                if verb in (
                    "configuring",
                    "generating",
                    "compiling",
                    "linking",
                    "building",
                    "installing",
                ):
                    keep.append(line)
                    continue
                # Default for "-- Something: value" lines
                if ":" in rest or "=" in rest:
                    target_lines.append(line)
                    continue
                suppressed += 1
                continue

            if _FEATURE_RE.match(line):
                keep.append(line)
                continue

            if in_error_block and re.match(r"^\s", line):
                errors.append(line)
                continue

            if stripped.startswith("--"):
                keep.append(line)
                continue

            if _ERROR_RE.search(stripped):
                if "Warning" in stripped:
                    warnings.append(line)
                else:
                    errors.append(line)
                    in_error_block = False
                continue

            # Non-banner lines: keep but don't repeat
            keep.append(line)

        if not (verb_counts or errors or warnings or not_found or target_lines):
            return output

        result: list[str] = []
        if verb_counts:
            verbs = ", ".join(f"{v}={n}" for v, n in verb_counts.most_common())
            result.append(f"CMake configure: {sum(verb_counts.values())} checks ({verbs})")
        if not_found:
            result.append("Not found:")
            result.extend(f"  {line}" for line in not_found[:5])
        if target_lines:
            result.append("Detected:")
            for line in target_lines[:8]:
                result.append(f"  {line.strip()}")
            if len(target_lines) > 8:
                result.append(f"  ... ({len(target_lines) - 8} more)")
        if errors:
            result.append("Errors:")
            result.extend(f"  {line.strip()}" for line in errors[:5])
        if warnings:
            result.append("Warnings:")
            result.extend(f"  {line.strip()}" for line in warnings[:5])
            if len(warnings) > 5:
                result.append(f"  ... ({len(warnings) - 5} more)")
        # Keep any non-banner lines that look informative
        for line in keep:
            stripped = line.strip()
            if (
                "Configuring done" in stripped
                or "Generating done" in stripped
                or "Build files have been written" in stripped
                or "Configuring incomplete" in stripped
                or "errors occurred" in stripped
            ):
                result.append(stripped)
        return "\n".join(result)
