"""C/C++ build processor for compilers, Ninja, Meson, CMake, and Qt build tools."""

import re

from .base import Processor


class CppBuildProcessor(Processor):
    priority = 14
    hook_patterns = [
        r"^(gcc|g\+\+|clang|clang\+\+|cc|c\+\+)(?:\s|$)",
        r"^(ninja|meson(?:\s+(?:setup|compile))?|qmake|qmake6)(?:\s|$)",
        r"^cmake\s+--build\b",
        r"^(moc|moc-qt6|uic|uic-qt6|rcc|rcc-qt6)(?:\s|$)",
    ]

    @property
    def name(self) -> str:
        return "cpp_build"

    def can_handle(self, command: str) -> bool:
        return bool(
            re.search(
                r"(?:^|[;&]\s*)(?:\S+/)?(?:gcc|g\+\+|clang|clang\+\+|cc|c\+\+)"
                r"(?=\s|$)",
                command,
            )
            or re.search(
                r"(?:^|[;&]\s*)(?:\S+/)?(?:ninja|meson(?:\s+(?:setup|compile))?|"
                r"qmake6?|moc(?:-qt6)?|uic(?:-qt6)?|rcc(?:-qt6)?)\b",
                command,
            )
            or re.search(r"(?:^|[;&]\s*)cmake\s+--build\b", command)
        )

    def process(self, command: str, output: str) -> str:
        if not output or not output.strip() or "|" in command:
            return output

        lines = output.splitlines()
        if self._has_failure(lines):
            return self._extract_failures(lines)
        return self._summarize_success(lines)

    @staticmethod
    def _has_failure(lines: list[str]) -> bool:
        return any(
            re.search(
                r"\b(?:fatal error|error:|undefined reference|multiple definition|ld returned|"
                r"collect2: error|ninja: build stopped|FAILED:|AutoMoc error|AutoUic error|"
                r"RCC: Error|Project ERROR|CMake Error|FAILED)\b",
                line,
                re.IGNORECASE,
            )
            for line in lines
        )

    @staticmethod
    def _is_progress(line: str) -> bool:
        stripped = line.strip()
        return bool(
            re.match(r"^\[\d+/\d+\]\s+(?:Building|Linking|Generating|Automatic|Running)", stripped)
            or re.match(r"^\[\s*\d+%\]\s+(?:Building|Linking|Generating|Built target)", stripped)
            or re.match(
                r"^(?:Scanning dependencies|Consolidate compiler generated dependencies)",
                stripped,
            )
            or re.match(r"^(?:Entering|Leaving) directory ", stripped)
        )

    def _extract_failures(self, lines: list[str]) -> str:
        keep = [False] * len(lines)
        primary = re.compile(
            r"(?:^|\s)(?:fatal error|error:|warning:|note:|undefined reference|multiple definition|"
            r"ld returned|collect2: error|FAILED:|ninja: build stopped|AutoMoc error|AutoUic error|"
            r"RCC: Error|Project ERROR|CMake Error|FAILED)",
            re.IGNORECASE,
        )
        continuation = re.compile(
            r"^\s*(?:In file included from|from |required from|instantiated from|candidate:|"
            r"note:|help:|[~^]+\s*$|\d+\s*\||>>>|/\S+|[A-Za-z]:\\)"
        )

        for i, line in enumerate(lines):
            if primary.search(line):
                for j in range(max(0, i - 2), min(len(lines), i + 5)):
                    if not self._is_progress(lines[j]):
                        keep[j] = True
            elif continuation.search(line):
                keep[i] = True

        result = [line for i, line in enumerate(lines) if keep[i] and line.strip()]
        return "\n".join(result) if result else "\n".join(lines[-40:])

    def _summarize_success(self, lines: list[str]) -> str:
        warnings = [line.strip() for line in lines if re.search(r"\bwarning:", line, re.I)]
        meaningful = [
            re.sub(r"^\[\s*\d+(?:/\d+|%)\]\s*", "", line.strip())
            for line in lines
            if line.strip()
            and re.search(
                r"(?:built target|build finished|build files have been written|"
                r"ninja: no work to do|linking|generated|installing|total time)",
                line,
                re.I,
            )
        ]
        summary = "C/C++ build succeeded."
        if warnings:
            summary += f" ({len(warnings)} warnings)"
        result = [summary]
        result.extend(f"  {line}" for line in warnings[:10])
        if len(warnings) > 10:
            result.append(f"  ... ({len(warnings) - 10} more warnings)")
        result.extend(meaningful[-5:])
        return "\n".join(dict.fromkeys(result))
