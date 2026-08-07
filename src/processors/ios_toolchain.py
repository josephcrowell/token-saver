"""iOS / macOS toolchain processor: fastlane, CocoaPods, and Swift Package Manager.

Recognized commands:
  - fastlane lanes and tools (`fastlane ios build`, `fastlane beta`, `bundle exec fastlane`)
  - CocoaPods (`pod install`, `pod update`, `pod repo update`, `pod search`, `pod lib`)
  - Swift Package Manager (`swift build`, `swift test`, `swift package resolve`,
    `swift package update`, `swift package show-dependencies`)

The output of these tools is dominated by shell-like progress, network
fetch, file-copy, and dependency-resolution noise.  We preserve the final
result, errors, warnings, and the structured outcome of each step.
"""

import re
from collections import Counter

from .base import Processor

# ── Output patterns ────────────────────────────────────────────────
_POD_INSTALL_RE = re.compile(
    r"^\s*(?:\x1b\[[0-9;]*m)?(Installing|Analyzing|Downloading|Removing|"
    r"Updating|Cleaning|Pod |-> )"
)
_POD_PROGRESS_RE = re.compile(
    r"^\s*(?:\x1b\[[0-9;]*m)?Downloading ->\s+\S+\s+\([\d.]+ (?:KB|MB)\s*of\s*"
    r"[\d.]+ (?:KB|MB)\)"
)
_FASTLANE_RE = re.compile(
    r"^\s*(?:\x1b\[[0-9;]*m)?\[(\d{2}:\d{2}:\d{2})\]:\s+(?P<rest>.*)$"
)
_SPM_PROGRESS_RE = re.compile(
    r"^(?:\x1b\[[0-9;]*m)?(Computing (?:version|range)|"
    r"Cloning|Resolving|Updating|Fetching|Checking out|"
    r"Compiling|Linking|Generating|Emitting|"
    r"Build complete!|Test (?:Suite|Suite.+failed)|"
    r"warning:|error:)\b"
)
_SPM_TEST_RE = re.compile(
    r"^(?P<ind>\s*)(Test Suite '[^']+' (?P<status>passed|failed|skipped)\b.*)$"
)
_POD_PODFILE_RE = re.compile(r"Pod installation complete!|Pod install.*complete")


class IOSToolchainProcessor(Processor):
    priority = 16.5
    hook_patterns = [
        r"^(?:\S*/)?fastlane\b",
        r"^(?:\S*/)?pod\b",
        r"^(?:\S*/)?swift\s+(?:build|test|run|package)\b",
        r"^bundle\s+exec\s+fastlane\b",
        r"^xcodebuild\b",
    ]

    @property
    def name(self) -> str:
        return "ios_toolchain"

    def can_handle(self, command: str) -> bool:
        return bool(
            re.search(
                r"(?:^|[;&]\s*)(?:\S*/)?fastlane\b",
                command,
            )
            or re.search(
                r"(?:^|[;&]\s*)(?:\S*/)?pod\s+(?:install|update|repo|search|lib|trunk|spec|deintegrate)\b",
                command,
            )
            or re.search(
                r"(?:^|[;&]\s*)(?:\S*/)?swift\s+(?:build|test|run|package)\b",
                command,
            )
            or re.search(
                r"(?:^|[;&]\s*)bundle\s+exec\s+fastlane\b",
                command,
            )
            or re.search(
                r"(?:^|[;&]\s*)xcodebuild\b",
                command,
            )
        )

    def process(self, command: str, output: str) -> str:
        if not output or not output.strip() or "|" in command:
            return output

        if re.search(r"\bpod\s+(?:install|update|repo)\b", command):
            return self._process_pod(output)
        if re.search(r"\b(?:swift\s+package|swift\s+build|swift\s+test)\b", command):
            return self._process_spm(output)
        if re.search(r"\bfastlane\b|\bbundle\s+exec\s+fastlane\b", command):
            return self._process_fastlane(output)
        if re.search(r"\bxcodebuild\b", command):
            return self._process_xcodebuild(output)
        return output

    # ── pod ─────────────────────────────────────────────────────────
    def _process_pod(self, output: str) -> str:
        lines = output.splitlines()
        verb_counts: Counter[str] = Counter()
        errors: list[str] = []
        warnings: list[str] = []
        pod_lines: list[str] = []
        in_error_block = False
        error_block: list[str] = []
        suppressed = 0
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if _POD_PODFILE_RE.search(stripped):
                pod_lines.append(stripped)
                continue
            if _POD_PROGRESS_RE.match(stripped):
                verb_counts["downloading"] += 1
                suppressed += 1
                continue
            m = _POD_INSTALL_RE.match(stripped)
            if m:
                verb = m.group(1).strip().lower()
                verb_counts[verb] = verb_counts.get(verb, 0) + 1
                if "error" in stripped.lower():
                    errors.append(stripped)
                elif "warning" in stripped.lower():
                    warnings.append(stripped)
                suppressed += 1
                continue
            if re.search(r"(?i)\b(?:error[:!]|FATAL|Unable to find|cannot find|"
                         r"podfile.*error)\b", stripped):
                in_error_block = True
                error_block.append(line)
                continue
            if in_error_block:
                if re.match(r"^\s", line) or stripped.startswith("#") or "!" in stripped:
                    error_block.append(line)
                    continue
                if error_block:
                    errors.append("\n".join(error_block).strip())
                error_block = []
                in_error_block = False
            if re.search(r"(?i)\bwarning\b", stripped) and "!" not in stripped:
                warnings.append(stripped)
                continue
            if "Pods" in stripped and ("installed" in stripped or "updated" in stripped):
                pod_lines.append(stripped)
                continue

        if in_error_block and error_block:
            errors.append("\n".join(error_block).strip())

        if not (verb_counts or errors or warnings or pod_lines):
            return output

        result: list[str] = []
        if verb_counts:
            verbs = ", ".join(f"{v}={n}" for v, n in verb_counts.most_common())
            result.append(f"Pod: {sum(verb_counts.values())} events ({verbs})")
        if pod_lines:
            result.extend(pod_lines)
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

    # ── fastlane ────────────────────────────────────────────────────
    def _process_fastlane(self, output: str) -> str:
        lines = output.splitlines()
        actions: list[str] = []
        errors: list[str] = []
        warnings: list[str] = []
        keep: list[str] = []
        in_error_block = False
        error_block: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            m = _FASTLANE_RE.match(stripped)
            if m:
                rest = m.group("rest")
                # Detect action names
                if re.match(r"---+\s*$", rest):
                    continue
                if "fastlane.tools" in rest and "sending" in rest.lower():
                    continue
                if "Successfully" in rest or "BUILD SUCCEEDED" in rest:
                    keep.append(stripped)
                    continue
                step_m = re.match(r"---+\s*Step:\s*(\S+)", rest)
                if step_m:
                    actions.append(step_m.group(1))
                    continue
                if re.match(r"^(\+\s*)?[A-Z][\w. ]+", rest) and ":" not in rest.split(" ")[0]:
                    actions.append(rest)
                    continue
                keep.append(stripped)
                continue
            if re.search(r"(?i)\berror[:!]|FastlaneError|❌", stripped):
                in_error_block = True
                error_block.append(line)
                continue
            if in_error_block:
                if re.match(r"^\s", line) or stripped.startswith(("+", "!", "$")):
                    error_block.append(line)
                    continue
                if error_block:
                    errors.append("\n".join(error_block).strip())
                error_block = []
                in_error_block = False
            if "⚠️" in stripped or re.search(r"(?i)\bwarning\b", stripped):
                warnings.append(stripped)
                continue

        if in_error_block and error_block:
            errors.append("\n".join(error_block).strip())

        if not (actions or errors or warnings or keep):
            return output

        result: list[str] = []
        if actions:
            unique = list(dict.fromkeys(actions))[:12]
            result.append("Fastlane actions:")
            result.extend(f"  {a}" for a in unique)
            if len(actions) > len(unique):
                result.append(f"  ... ({len(actions) - len(unique)} more)")
        if keep:
            result.append("Result:")
            for line in keep[-3:]:
                result.append(f"  {line}")
        if errors:
            result.append("Errors:")
            for block in errors[:5]:
                result.append(block)
                result.append("")
        if warnings:
            for line in warnings[:3]:
                result.append(f"Warning: {line}")
        return "\n".join(result).rstrip()

    # ── swift package / build / test ────────────────────────────────
    def _process_spm(self, output: str) -> str:
        lines = output.splitlines()
        verb_counts: Counter[str] = Counter()
        errors: list[str] = []
        warnings: list[str] = []
        tests: list[str] = []
        keep: list[str] = []
        in_error_block = False
        error_block: list[str] = []
        suppressed = 0
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            m = _SPM_TEST_RE.match(line)
            if m:
                # Capture status plus the test name (everything between
                # the leading/trailing single quotes in the suite name)
                suite = re.search(r"Test Suite '([^']+)'", line)
                name = f"{suite.group(1)}: " if suite else ""
                tests.append(f"{name}{m.group('status')}")
                continue
            m = _SPM_PROGRESS_RE.match(stripped)
            if m:
                verb = m.group(1).strip().lower()
                verb_counts[verb] = verb_counts.get(verb, 0) + 1
                if verb == "error:":
                    errors.append(stripped)
                elif verb == "warning:":
                    warnings.append(stripped)
                suppressed += 1
                continue
            if re.search(r"(?i)\b(?:error[:!]|FATAL|cannot find|undefined symbol)\b", stripped):
                in_error_block = True
                error_block.append(line)
                continue
            if in_error_block:
                if re.match(r"^\s", line):
                    error_block.append(line)
                    continue
                if error_block:
                    errors.append("\n".join(error_block).strip())
                error_block = []
                in_error_block = False
            if "Build complete!" in stripped or "Test Suite 'All tests" in stripped:
                keep.append(stripped)
                continue

        if in_error_block and error_block:
            errors.append("\n".join(error_block).strip())

        if not (verb_counts or errors or warnings or tests or keep):
            return output

        result: list[str] = []
        if verb_counts:
            verbs = ", ".join(f"{v}={n}" for v, n in verb_counts.most_common())
            result.append(f"Swift: {sum(verb_counts.values())} events ({verbs})")
        if tests:
            passed = sum(1 for t in tests if "passed" in t)
            failed = sum(1 for t in tests if "failed" in t)
            skipped = sum(1 for t in tests if "skipped" in t)
            result.append(f"Tests: {passed} passed, {failed} failed, {skipped} skipped")
            for t in tests[:5]:
                result.append(f"  {t}")
        if keep:
            for i in range(max(0, len(keep) - 3), len(keep)):
                result.append(keep[i])
        if errors:
            result.append("Errors:")
            for block in errors[:5]:
                result.append(block)
                result.append("")
        if warnings:
            for line in warnings[:3]:
                result.append(f"Warning: {line}")
        return "\n".join(result).rstrip()

    # ── xcodebuild ──────────────────────────────────────────────────
    def _process_xcodebuild(self, output: str) -> str:
        lines = output.splitlines()
        errors: list[str] = []
        warnings: list[str] = []
        keep: list[str] = []
        result_summary: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if re.search(
                r"^\*\* (BUILD|TEST|ARCHIVE|CLEAN) "
                r"(SUCCEEDED|FAILED|INTERRUPTED) \*\*",
                stripped,
            ):
                result_summary.append(stripped)
                continue
            m = re.search(r"^(/.+?):(\d+):(\d+):\s+(error|warning):\s*(.+)$", stripped)
            if m:
                if m.group(4) == "error":
                    errors.append(stripped)
                else:
                    warnings.append(stripped)
                continue
            if re.search(r"^(ld:|ld -)|error: |fatal error:", stripped):
                errors.append(stripped)
                continue
            # Strip the verbose step list
            if re.match(r"^\s*PhaseScriptExecution\s|\s*CompileC\s|\s*Ld ", stripped):
                continue
            if "Touching" in stripped and "app.dSYM" in stripped:
                keep.append(stripped)
                continue
        if not (errors or warnings or result_summary or keep):
            return output
        result: list[str] = []
        if result_summary:
            result.extend(result_summary)
        if errors:
            result.append("Errors:")
            result.extend(f"  {e}" for e in errors[:10])
        if warnings:
            result.append(f"Warnings: {len(warnings)}")
            for w in warnings[:3]:
                result.append(f"  {w}")
        if keep:
            for i in range(min(2, len(keep))):
                result.append(keep[i])
        return "\n".join(result).rstrip()
