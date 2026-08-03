"""CTest, GoogleTest, Catch2, Qt Test, and QML test output processor."""

import re

from .base import Processor


class CppTestProcessor(Processor):
    priority = 13
    hook_patterns = [
        r"^(ctest|qmltestrunner)(?:\s|$)",
        r"^\S*(?:test|tests|tst_\w+)(?:\.exe)?(?:\s+.*)?(?:--gtest_|--reporter|-[ox])",
    ]

    @property
    def name(self) -> str:
        return "cpp_test"

    def can_handle(self, command: str) -> bool:
        if re.search(r"(?:^|[;&]\s*)(?:\S+/)?(?:ctest|qmltestrunner)\b", command):
            return True
        return bool(
            re.search(
                r"--gtest_(?:filter|output|repeat|shuffle)|--reporter\s+|(?:^|/)tst_\w+",
                command,
            )
        )

    def process(self, command: str, output: str) -> str:
        if not output or not output.strip():
            return output
        lines = output.splitlines()
        if re.search(r"\bctest\b", command):
            return self._process_ctest(lines)
        return self._process_framework(lines)

    @staticmethod
    def _process_ctest(lines: list[str]) -> str:
        failures: list[str] = []
        summaries: list[str] = []
        in_failure = False
        # Lines worth keeping inside a failure block.  Anything else (verbose
        # Qt Test output, LSAN leak dumps, full backtraces) is suppressed so
        # the model sees the signal without the noise.
        important = re.compile(
            r"^\*+\s*Start\s+testing\s+of\s+"
            r"|^\*+\s*Finished\s+testing\s+of\s+"
            r"|^\*+\s*(?:Failed|Exception)"
            r"|^\*+\s*(?:Stack\s+trace|Threading\s+helper|QObject::)"
            r"|^\s*(?:FAIL!|QFATAL|QASSERT|QERROR)\s*:"
            r"|^\s*(?:Actual|Expected|Loc)\b[^:\n]*:"
            r"|^Totals:"
            r"|^Config:\s+Using\s+QtTest"
            r"|^test_\w+\s+function\s+time:"
            r"|^Errors?\s+while\s+running\s+CTest"
            r"|^The\s+following\s+tests\s+FAILED:"
            r"|^\d+/\d+\s+Test\s+#\d+:\s+\S+\s+\*\*\*Failed"
            r"|^\s*Thread\s+\d+\s+\(Thread\s+0x"
        )
        # Stack frames (#N 0x...) are useful but verbose — cap per thread block.
        max_stack_per_thread = 5
        stack_count = 0

        for line in lines:
            stripped = line.strip()
            if re.search(
                r"\*\*\*(?:Failed|Exception)|The following tests FAILED|"
                r"Errors while running CTest",
                line,
            ):
                in_failure = True
                failures.append(line)
                continue
            if in_failure:
                if re.match(r"^\d+% tests passed", stripped):
                    in_failure = False
                    summaries.append(stripped)
                    continue
                if not stripped:
                    failures.append(line)
                    continue
                if important.match(line):
                    if re.match(r"^\s*Thread\s+\d+\s+\(Thread\s+0x", line):
                        stack_count = 0  # Reset per thread block
                    failures.append(line)
                    continue
                if re.match(r"^\s*#\d+\s+0x[0-9a-f]+\s+", line):
                    stack_count += 1
                    if stack_count <= max_stack_per_thread:
                        failures.append(line)
                    elif stack_count == max_stack_per_thread + 1:
                        failures.append(f"      ... ({stack_count + 5}+ more stack frames)")
                    continue
                continue
            if re.match(r"^(?:\d+% tests passed|Total Test time|No tests were found)", stripped):
                summaries.append(stripped)
        if failures:
            return "\n".join([*failures, *summaries])
        return "\n".join(summaries) if summaries else "CTest passed."

    @staticmethod
    def _process_framework(lines: list[str]) -> str:
        failures: list[str] = []
        summaries: list[str] = []
        in_failure = False
        important = re.compile(
            r"^\*+\s*(?:Start|Finished)\s+testing\s+of\s+"
            r"|^\*+\s*(?:Failed|Exception|Stack\s+trace)"
            r"|^\s*(?:FAIL!|QFATAL|QASSERT|QERROR)\s*:"
            r"|^\s*(?:Actual|Expected|Loc)\b[^:\n]*:"
            r"|^Totals:"
            r"|^Config:\s+Using\s+QtTest"
            r"|^\s*Thread\s+\d+\s+\(Thread\s+0x"
        )
        max_stack_per_thread = 5
        stack_count = 0
        for line in lines:
            stripped = line.strip()
            if re.search(
                r"(?:^FAIL!|^FAIL\s|\[\s*FAILED\s*\]|FAILED:|fatal error|Actual\s*:|Expected\s*:)",
                stripped,
                re.I,
            ):
                in_failure = True
                failures.append(line)
                continue
            if in_failure:
                if not stripped:
                    failures.append(line)
                    continue
                if important.match(line):
                    if re.match(r"^\s*Thread\s+\d+\s+\(Thread\s+0x", line):
                        stack_count = 0
                    failures.append(line)
                    continue
                if re.match(r"^\s+#\d+\s+0x[0-9a-f]+\s+", line):
                    stack_count += 1
                    if stack_count <= max_stack_per_thread:
                        failures.append(line)
                    elif stack_count == max_stack_per_thread + 1:
                        failures.append("      ... (more stack frames)")
                    continue
                # Drop verbose PASS/QDEBUG noise inside failure blocks
                continue
            if re.search(
                r"(?:Totals:|tests? passed|tests? failed|test cases:|assertions:|"
                r"\[=+\].*tests? from)",
                stripped,
                re.I,
            ):
                summaries.append(stripped)
        if failures:
            return "\n".join([*failures, *summaries])
        return "\n".join(summaries) if summaries else "C++/Qt tests passed."
