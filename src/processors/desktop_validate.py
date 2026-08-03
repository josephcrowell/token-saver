"""desktop-file-validate output processor.

Validation output repeats `<file>: error: <message>` / `warning:` / `hint:`
per key violation, often thousands of lines when run over a directory tree.
Groups violations by file, and by rule across files.
"""

import re

from .base import Processor

_LINE_RE = re.compile(
    r"^(?P<file>[^:]+?\.desktop):\s+(?P<level>error|warning|hint):\s+(?P<msg>.+)$"
)


class DesktopValidateProcessor(Processor):
    priority = 16
    hook_patterns = [
        r"^desktop-file-validate\b",
    ]

    @property
    def name(self) -> str:
        return "desktop_validate"

    def can_handle(self, command: str) -> bool:
        # The tool name is distinctive; match it anywhere (direct call,
        # xargs, find -exec, for-loops).
        return bool(re.search(r"\bdesktop-file-validate\b", command))

    def process(self, command: str, output: str) -> str:
        if not output or not output.strip():
            return output

        by_file: dict[str, list[str]] = {}
        by_rule: dict[str, list[str]] = {}
        unparsed: list[str] = []

        for line in output.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            m = _LINE_RE.match(stripped)
            if m:
                by_file.setdefault(m.group("file"), []).append(
                    f"{m.group('level')}: {m.group('msg')}"
                )
                # Normalize message to a rule key (strip quoted values)
                rule = re.sub(r'"[^"]*"', '"…"', m.group("msg"))
                by_rule.setdefault(f"{m.group('level')}: {rule}", []).append(m.group("file"))
            else:
                unparsed.append(stripped)

        if not by_file:
            return output

        errors = sum(1 for msgs in by_file.values() for m in msgs if m.startswith("error:"))
        warnings = sum(1 for msgs in by_file.values() for m in msgs if m.startswith("warning:"))
        hints = sum(1 for msgs in by_file.values() for m in msgs if m.startswith("hint:"))

        result = [
            (
                f"desktop-file-validate: {errors} error(s), {warnings} warning(s), "
                f"{hints} hint(s) in {len(by_file)} file(s)."
            )
        ]

        # Most common rules across files
        result.append("Top violations:")
        for rule, files in sorted(by_rule.items(), key=lambda kv: -len(kv[1]))[:8]:
            sample = files[0]
            extra = f" (+{len(files) - 1} more files)" if len(files) > 1 else ""
            result.append(f"  [{len(files)}x] {rule} — {sample}{extra}")

        # Files with the most violations
        result.append("Worst files:")
        for f, msgs in sorted(by_file.items(), key=lambda kv: -len(kv[1]))[:8]:
            result.append(f"  {f} ({len(msgs)})")
            for msg in msgs[:3]:
                result.append(f"    {msg}")
            if len(msgs) > 3:
                result.append(f"    ... ({len(msgs) - 3} more)")

        if unparsed:
            result.append("Other output:")
            result.extend(f"  {u}" for u in unparsed[:10])
            if len(unparsed) > 10:
                result.append(f"  ... ({len(unparsed) - 10} more)")

        return "\n".join(result)
