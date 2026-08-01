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
        for line in lines:
            stripped = line.strip()
            if re.search(
                r"\*\*\*Failed|The following tests FAILED|Errors while running CTest",
                line,
            ):
                in_failure = True
                failures.append(line)
                continue
            if in_failure:
                if re.match(r"^\d+% tests passed", stripped):
                    in_failure = False
                    summaries.append(stripped)
                elif stripped:
                    failures.append(line)
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
            if in_failure and stripped:
                failures.append(line)
                if re.search(r"Totals:|tests? failed|\[=+\]", stripped, re.I):
                    in_failure = False
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
