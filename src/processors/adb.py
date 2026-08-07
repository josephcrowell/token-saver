"""Android Debug Bridge (adb) processor.

Compresses verbose adb subcommands:

- `adb install` / `adb uninstall` — keeps status, collapses stream progress.
- `adb shell pm list packages` — collapses to a count and a few example
  package names.
- `adb shell pm uninstall` / `adb shell monkey` — keeps the full output.
- `adb logcat` — collapses timestamp/level repetition; keeps the most recent
  lines and any error/stack frames.
- `adb pull` / `adb push` — keeps byte counts and status.
"""

import re

from .base import Processor

# ── Output patterns ────────────────────────────────────────────────
_ADB_STREAM_RE = re.compile(r"^\s*\[\s*\d+%\s*\]\s*")
_ADB_PERF_RE = re.compile(
    r"^Total\s+transfer\s+rate:.*$",
    re.IGNORECASE,
)
_PM_PACKAGE_RE = re.compile(r"^package:(?P<pkg>[\w.\-]+)\s*$")
_PM_USER_RE = re.compile(
    r"^Success(?:es)?(?:\s+for\s+(?P<user>\S+))?:?",
    re.IGNORECASE,
)
_LOGCAT_LINE_RE = re.compile(
    r"^(?P<ts>\d{1,2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3})"
    r"\s+(?P<pid>\d+)\s+(?P<tid>\d+)\s+(?P<level>[VDIWEFS])\s+"
    r"(?P<tag>[^:]+):\s+(?P<msg>.*)$"
)
_LOGCAT_FATAL_RE = re.compile(
    r"\b(FATAL|EXCEPTION|ANR|StackTrace|java\.lang\.|AndroidRuntime)\b"
)


class AdbProcessor(Processor):
    priority = 20.5
    hook_patterns = [
        r"^(?:\S*/)?adb\b",
    ]

    @property
    def name(self) -> str:
        return "adb"

    def can_handle(self, command: str) -> bool:
        return bool(re.search(r"(?:^|[;&]\s*)(?:\S*/)?adb\b", command))

    def process(self, command: str, output: str) -> str:
        if not output or not output.strip() or "|" in command:
            return output

        if re.search(r"\blogcat\b", command):
            return self._process_logcat(output)
        if re.search(r"\bpm\s+list\s+packages\b", command):
            return self._process_pm_list(output)
        if re.search(r"\binstall(?:-r|-t|-s|-d|-g|reinstall)?\b", command):
            return self._process_install(command, output)
        if re.search(r"\buninstall\b", command):
            return self._process_uninstall(output)
        if re.search(r"\b(?:pull|push)\b", command):
            return self._process_transfer(output)
        return output

    # ── logcat ──────────────────────────────────────────────────────
    def _process_logcat(self, output: str) -> str:
        lines = output.splitlines()
        total = len(lines)
        if total < 50:
            return output
        # Count by level
        level_counts: dict[str, int] = {}
        for line in lines:
            m = _LOGCAT_LINE_RE.match(line)
            if m:
                level_counts[m.group("level")] = level_counts.get(m.group("level"), 0) + 1
            elif _LOGCAT_FATAL_RE.search(line):
                level_counts["F"] = level_counts.get("F", 0) + 1

        # Find last fatal block
        last_fatal_idx = -1
        for i in range(total - 1, -1, -1):
            if _LOGCAT_FATAL_RE.search(lines[i]):
                last_fatal_idx = i
                break

        tail_size = 30
        head = []
        if last_fatal_idx >= 0:
            start = max(0, last_fatal_idx - 5)
            head = lines[start : last_fatal_idx + tail_size]
        else:
            head = lines[-tail_size:]

        parts = [f"logcat: {total} lines, levels={dict(sorted(level_counts.items()))}"]
        if head and head is not lines:
            parts.append("Last (most recent) entries:")
            parts.extend(head)
        return "\n".join(parts)

    # ── pm list packages ────────────────────────────────────────────
    def _process_pm_list(self, output: str) -> str:
        lines = [line for line in output.splitlines() if line.strip()]
        packages: list[str] = []
        for line in lines:
            m = _PM_PACKAGE_RE.match(line.strip())
            if m:
                packages.append(m.group("pkg"))
            else:
                packages.append(line.strip())
        if not packages:
            return output
        result = [f"pm list packages: {len(packages)} packages"]
        # Show first 5 and last 5
        for pkg in packages[:5]:
            result.append(f"  {pkg}")
        if len(packages) > 10:
            result.append("  ...")
            for pkg in packages[-5:]:
                result.append(f"  {pkg}")
        return "\n".join(result)

    # ── install / uninstall ─────────────────────────────────────────
    def _process_install(self, command: str, output: str) -> str:
        lines = [line for line in output.splitlines() if line.strip()]
        if not lines:
            return output
        result: list[str] = []
        for line in lines:
            stripped = line.strip()
            if _ADB_STREAM_RE.match(stripped):
                continue
            if re.match(r"^\s*adb\s+install\b", stripped):
                continue
            if "Performing Streamed Install" in stripped:
                result.append("Performing Streamed Install")
                continue
            if "Success" in stripped:
                result.append(stripped)
                continue
            if "Failure" in stripped or "INSTALL_FAILED" in stripped:
                result.append(stripped)
                continue
        if not result:
            return output
        return "\n".join(result)

    def _process_uninstall(self, output: str) -> str:
        lines = [line for line in output.splitlines() if line.strip()]
        if not lines:
            return output
        if any("Failure" in line or "not installed" in line for line in lines):
            return "\n".join(lines)
        if all("Success" in line for line in lines):
            return f"Uninstall OK ({len(lines)} entries)"
        return output

    # ── pull / push ─────────────────────────────────────────────────
    def _process_transfer(self, output: str) -> str:
        lines = [line for line in output.splitlines() if line.strip()]
        if not lines:
            return output
        # Strip percent-progress lines but keep the summary
        kept = [line for line in lines if not _ADB_STREAM_RE.match(line)]
        if not kept:
            return output
        return "\n".join(kept)
