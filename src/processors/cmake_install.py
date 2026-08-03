"""CMake install processor for cmake --install, make install, ninja install.

Install output is dominated by thousands of `-- Installing: <path>` and
`-- Up-to-date: <path>` lines (locale files, headers, site-packages).
Compresses to per-directory counts; keeps errors and RPATH notes.
"""

import re

from .base import Processor

_INSTALL_RE = re.compile(r"^-- (?:Installing|Up-to-date):\s+(\S+)")
_RPATH_RE = re.compile(r"^-- Set (?:non-toolchain portion of )?(?:runtime path|RPATH)")
# Case-sensitive on purpose: "Failed to find optional Qt component" (normal
# shiboken/cmake noise) must not match the ninja "FAILED:" failure marker.
_ERROR_RE = re.compile(r"CMake Error|FAILED:|\berror:|cannot find|No such file")


class CmakeInstallProcessor(Processor):
    # Must run before CppBuildProcessor (14): cpp_build claims any `ninja`
    # command, but `ninja install` output is install listing, not build noise.
    priority = 12
    hook_patterns = [
        r"^(?:\w+=\S+\s+)*cmake\s+--install\b",
        r"^(?:\w+=\S+\s+)*(?:make|ninja)\s+[^\n]*\binstall\b",
    ]

    @property
    def name(self) -> str:
        return "cmake_install"

    def can_handle(self, command: str) -> bool:
        return bool(
            re.search(r"(?:^|[;&]\s*)(?:\w+=\S+\s+)*cmake\s+--install\b", command)
            or re.search(
                r"(?:^|[;&]\s*)(?:\w+=\S+\s+)*(?:make|ninja)\s+[^\n;&]*\binstall\b",
                command,
            )
        )

    def process(self, command: str, output: str) -> str:
        if not output or not output.strip():
            return output

        lines = output.splitlines()
        installed_dirs: dict[str, int] = {}
        uptodate_dirs: dict[str, int] = {}
        errors: list[str] = []
        rpath_count = 0
        other: list[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            if _ERROR_RE.search(stripped):
                errors.append(stripped)
                continue

            if _RPATH_RE.match(stripped):
                rpath_count += 1
                continue

            m = _INSTALL_RE.match(stripped)
            if m:
                path = m.group(1)
                target = installed_dirs if stripped.startswith("-- Installing") else uptodate_dirs
                # Group by parent directory, collapsing deep paths
                parent = path.rsplit("/", 1)[0] if "/" in path else path
                target[parent] = target.get(parent, 0) + 1
                continue

            # Keep non-install informational lines that are short
            if stripped.startswith("--") and len(other) < 10:
                other.append(stripped)

        if errors:
            result = ["CMake install failed."]
            result.extend(errors[:30])
            if len(errors) > 30:
                result.append(f"... ({len(errors) - 30} more errors)")
            return "\n".join(result)

        total_new = sum(installed_dirs.values())
        total_old = sum(uptodate_dirs.values())
        result = [f"Install succeeded: {total_new} installed, {total_old} up-to-date."]

        def _fmt_dirs(dirs: dict[str, int], limit: int = 8) -> list[str]:
            items = sorted(dirs.items(), key=lambda kv: -kv[1])
            out = [f"    {d}/ ({n})" for d, n in items[:limit]]
            if len(items) > limit:
                out.append(f"    ... ({len(items) - limit} more directories)")
            return out

        if installed_dirs:
            result.append(f"  installed into {len(installed_dirs)} directorie(s):")
            result.extend(_fmt_dirs(installed_dirs))
        if uptodate_dirs and total_old:
            result.append(f"  up-to-date in {len(uptodate_dirs)} directorie(s)")
        if rpath_count:
            result.append(f"  RPATH adjusted on {rpath_count} file(s)")
        for line in other:
            if not _INSTALL_RE.match(line) and "Installing:" not in line:
                result.append(f"  {line}")
        return "\n".join(result)
