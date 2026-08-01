"""C/C++ and Qt static-analysis processor."""

import re
from collections import Counter, defaultdict

from .base import Processor


class CppAnalysisProcessor(Processor):
    priority = 17
    hook_patterns = [
        r"^(clang-tidy|clang-format|cppcheck|include-what-you-use|iwyu|qmllint|qmlformat)(?:\s|$)",
    ]

    @property
    def name(self) -> str:
        return "cpp_analysis"

    def can_handle(self, command: str) -> bool:
        return bool(
            re.search(
                r"(?:^|[;&]\s*)(?:\S+/)?(?:clang-tidy|clang-format|cppcheck|"
                r"include-what-you-use|iwyu|qmllint|qmlformat)\b",
                command,
            )
        )

    def process(self, command: str, output: str) -> str:
        if not output or not output.strip():
            return output

        diagnostics: list[str] = []
        context: list[str] = []
        rules: Counter[str] = Counter()
        examples: dict[str, list[str]] = defaultdict(list)
        lines = output.splitlines()

        diagnostic_re = re.compile(
            r"^(.*?):(\d+)(?::(\d+))?:\s*(warning|error|note|style|performance|portability|information):\s*(.*)$",
            re.I,
        )
        bracket_re = re.compile(r"\[([\w./-]+)\]\s*$")
        for line in lines:
            stripped = line.strip()
            match = diagnostic_re.match(stripped)
            if match:
                rule_match = bracket_re.search(stripped)
                rule = rule_match.group(1) if rule_match else match.group(4).lower()
                rules[rule] += 1
                if len(examples[rule]) < 5:
                    examples[rule].append(stripped)
                diagnostics.append(stripped)
                continue
            if diagnostics and re.match(r"^\s*(?:\d+\s*\||[~^]+|note:|help:)", line):
                context.append(line)

        if not diagnostics:
            if re.search(r"clang-format|qmlformat", command) and not output.strip():
                return output
            return output

        result = [f"{len(diagnostics)} C/C++/Qt analysis issues across {len(rules)} rules:"]
        for rule, count in rules.most_common():
            result.append(f"  {rule}: {count}")
            result.extend(f"    {line}" for line in examples[rule])
            if count > len(examples[rule]):
                result.append(f"    ... ({count - len(examples[rule])} more)")
        result.extend(context[:20])
        return "\n".join(result)
