"""Search output processor: grep -r, rg, ag, fd."""

import re
from collections import defaultdict

from .. import config
from .base import Processor


class SearchProcessor(Processor):
    priority = 35
    hook_patterns = [
        r"^(grep|rg|ag|fd|fdfind)\b",
    ]

    @property
    def name(self) -> str:
        return "search"

    def can_handle(self, command: str) -> bool:
        return bool(re.match(r"\s*(?:\S*/)?(grep|rg|ag|fd|fdfind)\b", command))

    def process(self, command: str, output: str) -> str:
        if not output or not output.strip():
            return output

        # fd/fdfind produces file listing output -- delegate to grouping
        if re.match(r"\s*(?:\S*/)?(?:fd|fdfind)\b", command):
            return self._process_fd(output)

        lines = output.splitlines()
        if len(lines) < 20:
            return output

        # Kilo's native grep tool renders matches as a file heading followed by
        # indented ``Line N: ...`` entries.  Parse that format before the
        # file:line:content parser below; otherwise the heading is counted as a
        # match while the actual match lines become unassociated plain text and
        # are dropped from the grouped output.
        native = self._parse_native_matches(lines)
        if native is not None:
            native_by_file, notices = native
            return "\n".join([self._format_grouped_matches(native_by_file), *notices])

        # An unfamiliar native annotation or explicitly requested context must
        # not fall back to a CLI parser that cannot associate it with its file.
        # Returning the original also tells the engine not to run generic
        # truncation. Prefer no savings to silently losing search evidence.
        if any(
            re.match(
                r"^\s*(?:Found \d+ match(?:es)?\b|(?:\[(?:match|context)\] )?Line \d+:)",
                line,
            )
            for line in lines
        ):
            return output

        # Detect format: file:line:content or file:content or just file
        by_file: dict[str, list[str]] = defaultdict(list)
        plain_matches = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # Skip binary file warnings
            if re.match(r"^Binary file .* matches", stripped):
                continue

            # file:line:content or file:content
            # Accept extensionless files if a line number follows
            m = re.match(r"^((?:[a-zA-Z]:)?[^\s:]+\.[a-zA-Z0-9]+):(\d+:)?(.*)$", stripped)
            if not m:
                m = re.match(r"^((?:[a-zA-Z]:)?[^\s:]+):(\d+:)(.*)$", stripped)
            if m:
                filepath = m.group(1)
                by_file[filepath].append(stripped)
            else:
                plain_matches.append(stripped)

        if not by_file and not plain_matches:
            return output

        total_files = len(by_file)

        if total_files == 0:
            # Plain list of matches -- just truncate
            if len(plain_matches) > 30:
                result = plain_matches[:25]
                result.append(f"... ({len(plain_matches) - 25} more matches)")
                return "\n".join(result)
            return output

        # Mixed/unknown CLI formats (e.g. paths with spaces or context lines)
        # cannot safely be grouped. Never count unparsed lines and then omit them.
        if plain_matches:
            return output

        return self._format_grouped_matches(by_file)

    @staticmethod
    def _parse_native_matches(
        lines: list[str],
    ) -> tuple[dict[str, list[str]], list[str]] | None:
        """Parse Kilo's file-heading/``Line N:`` search output format.

        Return ``None`` unless every non-empty, non-summary line belongs to a
        recognized native-grep block or limit notice. The caller must pass
        unrecognized native output through unchanged, not retry the CLI parser.
        Context-labelled results are deliberately passed through in full.
        """
        by_file: dict[str, list[str]] = defaultdict(list)
        current_file: str | None = None
        saw_detail = False
        notices: list[str] = []
        expected_matches: int | None = None

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            summary = re.fullmatch(
                r"Found (\d+) match(?:es)?(?:\s+(?:in|across)\s+\d+ files?)?"
                r"(?: (\(more matches available\)))?:?",
                stripped,
            )
            if summary and current_file is None and expected_matches is None:
                expected_matches = int(summary.group(1))
                if summary.group(2):
                    notices.append(summary.group(2))
                continue

            if saw_detail and re.fullmatch(
                r"\d+ matches limit reached\. Use limit=\d+ for more, or refine pattern\.",
                stripped,
            ):
                notices.append(stripped)
                continue

            detail = re.match(r"^\s+Line\s+\d+:", line)
            if detail and current_file:
                by_file[current_file].append(f"{current_file}:{stripped}")
                saw_detail = True
                continue

            # Native output uses an unindented path heading ending in ':'.
            # Do not accept whitespace here, so indented content cannot become
            # a new file accidentally.
            if not line[0].isspace() and stripped.endswith(":"):
                current_file = stripped[:-1]
                by_file.setdefault(current_file, [])
                continue

            return None

        if not saw_detail or any(not matches for matches in by_file.values()):
            return None
        if expected_matches is not None and expected_matches != sum(map(len, by_file.values())):
            return None
        return by_file, notices

    def _format_grouped_matches(
        self,
        by_file: dict[str, list[str]],
    ) -> str:
        """Format fully parsed file-grouped matches with explicit omissions."""
        total_matches = sum(len(v) for v in by_file.values())
        total_files = len(by_file)
        max_per_file = config.get("search_max_per_file")
        max_files = config.get("search_max_files")

        if total_files > 30:
            return self._process_grouped_by_dir(by_file, total_matches, total_files)

        result = [f"{total_matches} matches across {total_files} files:"]

        sorted_files = sorted(by_file.items(), key=lambda x: -len(x[1]))
        for filepath, matches in sorted_files[:max_files]:
            count = len(matches)
            if count > max_per_file:
                result.append(f"{filepath}: ({count} matches)")
                for match_line in matches[:max_per_file]:
                    # Strip the filepath prefix to avoid repetition
                    display = match_line
                    if display.startswith(filepath + ":"):
                        display = "  " + display[len(filepath) + 1 :]
                    else:
                        display = "  " + display
                    result.append(display)
                result.append(f"  ... ({count - max_per_file} more)")
            else:
                for match_line in matches:
                    result.append(match_line)

        if total_files > max_files:
            result.append(f"... ({total_files - max_files} more files)")

        return "\n".join(result)

    def _process_grouped_by_dir(
        self,
        by_file: dict,
        total_matches: int,
        total_files: int,
    ) -> str:
        """Group search results by directory for large result sets."""
        max_per_file = config.get("search_max_per_file")
        max_files = config.get("search_max_files")

        by_dir: dict[str, dict[str, list[str]]] = {}
        for filepath, matches in by_file.items():
            parts = filepath.rsplit("/", 1)
            dir_name = parts[0] if len(parts) > 1 else "."
            by_dir.setdefault(dir_name, {})[filepath] = matches

        result = [
            f"{total_matches} matches across {total_files} files in {len(by_dir)} directories:"
        ]

        dirs_shown = 0
        for dir_name, files in sorted(
            by_dir.items(), key=lambda x: -sum(len(v) for v in x[1].values())
        ):
            if dirs_shown >= max_files:
                break
            dir_matches = sum(len(v) for v in files.values())
            result.append(f"\n{dir_name}/ ({dir_matches} matches in {len(files)} files)")

            # Show top 3 files in this directory
            for filepath, matches in sorted(files.items(), key=lambda x: -len(x[1]))[:3]:
                fname = filepath.rsplit("/", 1)[-1]
                if len(matches) > max_per_file:
                    result.append(f"  {fname}: ({len(matches)} matches)")
                    for m in matches[:max_per_file]:
                        display = m[len(filepath) + 1 :] if m.startswith(filepath + ":") else m
                        result.append(f"    {display}")
                else:
                    for m in matches:
                        result.append(f"  {m}")

            remaining_files = len(files) - 3
            if remaining_files > 0:
                result.append(f"  ... ({remaining_files} more files in this directory)")

            dirs_shown += 1

        remaining_dirs = len(by_dir) - dirs_shown
        if remaining_dirs > 0:
            result.append(f"\n... ({remaining_dirs} more directories)")

        return "\n".join(result)

    def _process_fd(self, output: str) -> str:
        """Compress fd/fdfind output: group by directory."""
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        if len(lines) < 20:
            return output

        by_dir: dict[str, list[str]] = defaultdict(list)
        for path in lines:
            parts = path.rsplit("/", 1)
            dir_name = parts[0] if len(parts) > 1 else "."
            file_name = parts[-1] if len(parts) > 1 else path
            by_dir[dir_name].append(file_name)

        max_files = config.get("search_max_files")

        result = [f"{len(lines)} files found:"]
        dirs = sorted(by_dir.items(), key=lambda x: -len(x[1]))
        for dir_path, files in dirs[:max_files]:
            if len(files) > 10:
                exts: dict[str, int] = defaultdict(int)
                for f in files:
                    ext = f.rsplit(".", 1)[-1] if "." in f else "(none)"
                    exts[ext] += 1
                ext_desc = ", ".join(
                    f"*.{e}:{n}" for e, n in sorted(exts.items(), key=lambda x: -x[1])[:4]
                )
                result.append(f"  {dir_path}/ ({len(files)} files: {ext_desc})")
            elif len(files) > 5:
                result.append(f"  {dir_path}/ ({len(files)} files): {', '.join(files[:3])} ...")
            else:
                for f in files:
                    result.append(f"  {dir_path}/{f}")

        if len(dirs) > max_files:
            result.append(f"... ({len(dirs) - max_files} more directories)")

        return "\n".join(result)
