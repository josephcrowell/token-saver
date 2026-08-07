"""Flutter / Dart processor for flutter, dart, and pub.dev tooling.

Recognized commands include `flutter build`, `flutter test`, `flutter pub get`,
`flutter pub deps`, `flutter analyze`, `flutter doctor`, `flutter run`, and
plain `dart` invocations.

Compresses the very chatty output these commands emit: dependency-resolution
progress, Gradle/Pod install progress, asset compilation, and analyzer
repetitive findings, while preserving all errors, stack traces, location
markers, and final result lines.
"""

import re

from .base import Processor

# ── Flutter command patterns ─────────────────────────────────────────
_Flutter_BUILD_RE = re.compile(
    r"\bflutter\s+(?:build\s+(?:apk|appbundle|ios|macos|linux|web|windows|aot|bnr)?"
    r"|run\s+|--?\S*)"
)
_DART_RE = re.compile(r"(?:^|[;&]\s*)(?:\S*/)?dart\s+(?:run|analyze|test|compile|pub|fmt|fix)\b")
_FLUTTER_PUB_RE = re.compile(r"\bflutter\s+pub(?:\s+(?:get|deps|outdated|upgrade|run))?\b")
_FLUTTER_DOCTOR_RE = re.compile(r"\bflutter\s+doctor(?:\s+-v)?\b")
_FLUTTER_ANALYZE_RE = re.compile(r"\bflutter\s+analyze\b")
_FLUTTER_RE = re.compile(
    r"(?:^|[;&]\s*)(?:\S*/)?flutter\s+(?:-h|help|build|run|test|pub|analyze|doctor|clean|upgrade|precache|assemble|format|fix|screenshot|driver|version)\b"
)


# ── Output parsers ───────────────────────────────────────────────────
_DEP_PROGRESS_RE = re.compile(
    r"^[\s|]*(?:Got dependencies!|Resolving dependencies|Resolving versions|Downloading packages|"
    r"Built build\.|Built .+\.dart|"
    r"\.pub-cache|Downloading [A-Za-z0-9_.-]+|"
    r"\d+% \d+/\d+(?:\s+\d+\.\d+ [KMG]?B)? \d+\.\d+s)"
)
_ASSET_COPY_RE = re.compile(r"^[\s|]*✓\s+Built\s+")
_GRADLE_PROXY_RE = re.compile(
    r"^(?:Resolving|Downloading|Checking|Caching|Computing|Building|Finalizing)\s+"
)
_ANALYZE_INFO_RE = re.compile(r"^\s+(?:info|warning|hint)\s+•\s+")
_DOCTOR_CHECK_RE = re.compile(
    r"^\s*\[\s*(?P<mark>[✓✗!])\s*\]\s+(?P<check>.+?)$",
    re.UNICODE,
)
_ERROR_RE = re.compile(
    r"(?:^|\s)(?:Error|error|ERROR|Failed|FAILED|FATAL|Exception|Exception:|throw |"
    r"Could not|cannot find|Cannot find|undefined reference|undefined symbol|"
    r"no such file|not found|"
    r"\bFATAL\b|\bEXCEPTION\b|\bPANIC\b)",
)
_LOCATION_RE = re.compile(
    r"^(?:.+?\.(?:dart|kt|swift|java|gradle|yaml|json|lock|pub-cache)?:\d+(?::\d+)?)"
    r"|Error on line \d+",
    re.IGNORECASE,
)
_DOCTOR_HEADER_RE = re.compile(r"^\s+Doctor summary(?:\.|$)")


class FlutterProcessor(Processor):
    # Above Maven/Gradle (28) and above build (25) so Flutter wins for
    # `flutter build apk` even when its sub-commands would otherwise match
    # build, maven_gradle, or cpp_build.
    priority = 10
    hook_patterns = [
        r"^(?:\S*/)?flutter\b",
        r"^(?:\S*/)?dart\s+(?:run|analyze|test|compile|pub|fmt|fix)\b",
    ]

    @property
    def name(self) -> str:
        return "flutter"

    def can_handle(self, command: str) -> bool:
        return bool(
            re.search(
                r"(?:^|[;&]\s*)(?:\S*/)?flutter\s+[a-zA-Z]",
                command,
            )
            or _DART_RE.search(command)
            or _FLUTTER_RE.search(command)
        )

    def process(self, command: str, output: str) -> str:
        if not output or not output.strip() or "|" in command:
            return output

        if _FLUTTER_DOCTOR_RE.search(command):
            return self._process_doctor(output)
        if _FLUTTER_ANALYZE_RE.search(command):
            return self._process_analyze(output)
        if _FLUTTER_PUB_RE.search(command) and not re.search(
            r"\bflutter\s+(?:build|run|test)\b", command
        ):
            return self._process_pub(output)
        return self._process_build(output)

    # ── doctor ──────────────────────────────────────────────────────
    def _process_doctor(self, output: str) -> str:
        lines = output.splitlines()
        checks: list[str] = []
        problems: list[str] = []
        in_problem = False
        problem_block: list[str] = []
        in_summary = False

        for line in lines:
            stripped = line.strip()
            m = _DOCTOR_CHECK_RE.match(stripped)
            if m:
                if problem_block and in_problem:
                    problems.append(" ".join(problem_block).strip())
                problem_block = []
                in_problem = m.group("mark") == "✗"
                checks.append(f"[{m.group('mark')}] {m.group('check')}")
                continue
            if _DOCTOR_HEADER_RE.match(stripped):
                if problem_block:
                    problems.append(" ".join(problem_block).strip())
                problem_block = []
                in_summary = True
                continue
            should_capture = in_problem and stripped
            if (in_summary and should_capture) or (should_capture and not in_summary):
                problem_block.append(stripped)

        if problem_block and in_problem:
            problems.append(" ".join(problem_block).strip())

        if not checks:
            return output

        ok = sum(1 for c in checks if c.startswith("[✓]"))
        bad = sum(1 for c in checks if c.startswith("[✗]"))
        warn = sum(1 for c in checks if c.startswith("[!]"))
        result = [f"Flutter doctor: {ok} ok, {bad} problems, {warn} warnings"]
        if problems:
            result.extend(problems[:5])
        else:
            for c in checks:
                if c.startswith(("[✗]", "[!]")):
                    result.append(f"  {c}")
        return "\n".join(result)

    # ── analyze ─────────────────────────────────────────────────────
    def _process_analyze(self, output: str) -> str:
        lines = output.splitlines()
        errors: list[str] = []
        warnings: list[str] = []
        infos: list[str] = []
        final_lines: list[str] = []
        summary_lines: list[str] = []
        saw_summary = False
        last_block_rule: list[str] = []
        # Old format: rule on one line, location on next
        # New format: rule and location on same line, e.g.
        #   error - Undefined class 'Foo' at lib/main.dart:5:1
        # Newer format: separate rule and location lines but indented
        inline_re = re.compile(
            r"^\s*(?P<severity>error|warning|info|hint)\s+-\s+"
            r"(?P<message>.+?)\s+at\s+(?P<file>[^:]+):(?P<line>\d+):\d+\s*$",
            re.IGNORECASE,
        )
        rule_re = re.compile(
            r"^\s*(?P<severity>error|warning|info|hint)\s+-\s+(?P<message>.+?)\s*$",
            re.IGNORECASE,
        )
        location_re = re.compile(
            r"^\s*(?P<file>[^:]+?\.dart)\s+(?P<line>\d+):\d+\s*$",
        )

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if re.match(r"^Analyzing\s+", stripped):
                continue
            if re.match(r"^No issues found", stripped, re.IGNORECASE):
                summary_lines.append(stripped)
                continue
            if re.match(r"^\d+ (?:issue|warning|error|info|hint)", stripped, re.IGNORECASE):
                summary_lines.append(stripped)
                saw_summary = True
                continue
            if saw_summary:
                final_lines.append(line)
                continue
            m = inline_re.match(line)
            if m:
                finding = (
                    f"{m.group('file')}:{m.group('line')}: "
                    f"{m.group('severity')}: {m.group('message')}"
                )
                severity = m.group("severity").lower()
                if severity == "error":
                    errors.append(finding)
                elif severity == "warning":
                    warnings.append(finding)
                else:
                    infos.append(finding)
                continue
            m = rule_re.match(line)
            if m:
                last_block_rule.append(m.group(0))
                continue
            m = location_re.match(line)
            if m and last_block_rule:
                rule = last_block_rule[-1]
                finding_key = f"{m.group('file')}:{m.group('line')}"
                finding = f"{finding_key}: {rule.strip()}"
                severity = rule.split(" ", 1)[0].lower()
                if severity == "error":
                    errors.append(finding)
                elif severity == "warning":
                    warnings.append(finding)
                else:
                    infos.append(finding)
                last_block_rule = []
                continue
            if re.match(r"^\s+(?:error|warning|info|hint)\s+•", stripped, re.IGNORECASE):
                infos.append(stripped)
                continue

        if not (errors or warnings or infos):
            return output

        result: list[str] = []
        if errors:
            result.append(f"{len(errors)} errors:")
            result.extend(errors[:10])
        if warnings:
            result.append(f"{len(warnings)} warnings:")
            result.extend(warnings[:5])
            if len(warnings) > 5:
                result.append(f"  ... ({len(warnings) - 5} more)")
        if not errors and not warnings and infos:
            result.append(f"{len(infos)} infos:")
            result.extend(infos[:5])
        if summary_lines:
            result.extend(summary_lines)
        return "\n".join(result) if result else output

    # ── pub ─────────────────────────────────────────────────────────
    def _process_pub(self, output: str) -> str:
        lines = output.splitlines()
        deps_lines: list[str] = []
        top_level: list[str] = []
        sdk_lines: list[str] = []
        in_tree = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if not in_tree:
                if re.match(r"^(Dart SDK|Flutter SDK)\b", stripped):
                    sdk_lines.append(stripped)
                    continue
                # `flutter pub deps` always prints the root package and then
                # tree lines starting with ├, │, or └.  Anything that doesn't
                # is treated as preamble and dropped.
                if stripped.startswith(("├", "│", "└")):
                    in_tree = True
                else:
                    # Last-chance: the root package is plain (no markers)
                    if top_level or sdk_lines:
                        in_tree = True
                        continue
                    # The root line is the only preamble we want to keep
                    top_level.append(stripped)
                    continue
            deps_lines.append(stripped)
            if stripped.startswith(("├", "└")):
                _marker, _, rest = stripped.lstrip("├│└─").partition(" ")
                if not rest or rest.startswith(("├", "│", "└")):
                    pass
                # Top-level package (depth 0 in the printed tree)
                elif "│" not in stripped.split("─", 1)[0] + "x":
                    pkg = rest.split(" ", 1)[0]
                    if pkg not in top_level:
                        top_level.append(pkg)

        if "newer versions" in output:
            upgrades: list[str] = []
            for line in lines:
                if "newer versions" in line or "have newer versions incompatible" in line:
                    upgrades.append(line.strip())
        else:
            upgrades = []

        if deps_lines or top_level:
            result = [f"pub deps: {len(deps_lines)} entries, {len(top_level)} top-level"]
            if sdk_lines:
                result.append("  " + ", ".join(sdk_lines))
            if upgrades:
                result.append("Upgrades available:")
                result.extend(f"  {u}" for u in upgrades[:3])
            result.append("Top-level:")
            result.extend(f"  {d}" for d in top_level[:12])
            return "\n".join(result)

        # `pub get` / `pub upgrade`: collapse download progress to a count
        download_count = 0
        keep: list[str] = []
        errors: list[str] = []
        for line in lines:
            stripped = line.strip()
            if re.match(r"^(?:Downloading|Resolving|Computing|Caching|Built )", stripped):
                download_count += 1
                continue
            if _ERROR_RE.search(stripped) or "could not" in stripped.lower():
                errors.append(stripped)
                continue
            keep.append(stripped)

        result: list[str] = []
        if download_count:
            result.append(f"pub: {download_count} progress lines")
        if errors:
            result.append("Errors:")
            result.extend(errors[:5])
        if not errors and not download_count:
            return output
        for line in keep:
            if "Got dependencies" in line or "Resolving" in line or "No issues" in line:
                result.append(line)
        return "\n".join(result) if result else output

    # ── build / run / generic ───────────────────────────────────────
    def _process_build(self, output: str) -> str:
        lines = output.splitlines()
        errors: list[str] = []
        progress_count = 0
        progress_seen: set[str] = set()
        summary: list[str] = []
        in_error_block = False
        block: list[str] = []
        last: list[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if _DEP_PROGRESS_RE.match(stripped):
                if stripped not in progress_seen:
                    progress_count += 1
                    progress_seen.add(stripped)
                continue
            if _ASSET_COPY_RE.match(stripped):
                progress_count += 1
                continue
            if _GRADLE_PROXY_RE.match(stripped) and re.search(
                r"\d+\.\d+\s*s\b|^\s*\d+/\d+\s*$",
                stripped,
            ):
                progress_count += 1
                continue
            if _ERROR_RE.search(stripped) or stripped.startswith(("Error:", "FAILURE:")):
                if not in_error_block:
                    in_error_block = True
                    block = []
                block.append(line)
                continue
            if in_error_block:
                if _LOCATION_RE.match(stripped) or stripped.startswith(
                    ("at ", "Caused by", "  #", "#", "File ", "*")
                ):
                    block.append(line)
                    continue
                if re.match(r"^[-=]+\s*$", stripped):
                    continue
                if re.match(
                    r"^(?:\d+ (?:issue|warning|error|info|hint))",
                    stripped,
                    re.IGNORECASE,
                ):
                    errors.append("\n".join(block).strip())
                    block = []
                    in_error_block = False
                    continue
                if "Compiler" in stripped or "thrown" in stripped or "Exception" in stripped:
                    block.append(line)
                    continue
                # End of block
                if block:
                    errors.append("\n".join(block).strip())
                block = []
                in_error_block = False

            if re.match(
                r"^(?:\+|✓|✗|→|==>)\s+",
                stripped,
            ) and "built" in stripped.lower():
                last.append(stripped)
                continue
            if re.search(
                r"\b(?:BUILD SUCCESSFUL|BUILD FAILED|Successfully built|"
                r"Built .+\.apk|✓ Built)\b",
                stripped,
                re.I,
            ):
                summary.append(stripped)
                continue
            if re.search(r"\bRunning (?:Gradle task|Xcode build|flutter)", stripped, re.I):
                summary.append(stripped)
                continue
            if re.search(r"\berror found in the input\b", stripped, re.I):
                errors.append(stripped)
                continue

        if in_error_block and block:
            errors.append("\n".join(block).strip())

        if not (errors or progress_count or summary or last):
            return output

        result: list[str] = []
        if progress_count:
            result.append(f"Flutter: {progress_count} progress lines stripped")
        if summary:
            result.extend(summary)
        if last:
            result.extend(last[-3:])
        if errors:
            result.append("Errors:")
            for block in errors[:8]:
                result.append(block)
                result.append("")
        return "\n".join(result).rstrip()
