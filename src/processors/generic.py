"""Generic fallback processor: ANSI strip, dedup, whitespace collapse, truncation."""

import re

from .. import config
from .base import Processor
from ._signals.entropy import sticky_line_indices
from ._signals.error_detection import score_line

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b].*?\x07")

# Regex to normalize numbers/percentages for fuzzy matching
_NUMERIC_RE = re.compile(r"\d+(\.\d+)?")
# Unicode block/box characters are unambiguous progress bars.
_PROGRESS_BLOCK_RE = re.compile(r"[━█▓░▒■□●○]{3,}")
# ASCII runs (####, ====, ---->) are only progress bars in progress context;
# on their own they are usually separators / rules that must be preserved.
_ASCII_BAR_RE = re.compile(r"[#=\->]{5,}")
_PROGRESS_CONTEXT_RE = re.compile(r"[%\[\]]|\b\d+/\d+\b|ETA|eta|\d+(\.\d+)?\s*[KMGT]?i?B/s")

# Stack trace patterns from headroom log_compressor.py (L258–279)
# Fixed blank-line behavior: blank line inside trace does NOT terminate it
_STACK_TRACE_PATTERNS = [
    re.compile(r"^\s*at\s+"),  # Java/JavaScript stack frames
    re.compile(r"^\s*File\s+\"[^\"]+\".*line\s+\d+"),  # Python tracebacks
    re.compile(r"^\s*Traceback\s+\(most recent call last\):"),  # Python traceback header
    re.compile(r"^\s*from\s+"),  # Python continuation
    re.compile(r"^\s*\^\s*$"),  # Error pointer (Go, Rust)
    re.compile(r"^\s*\|\s*$"),  # Context marker
    re.compile(r"^\s*\-+\s*$"),  # Separator lines in traces
    re.compile(r"^\s*#\d+\s+0x[0-9a-fA-F]+\s+in\s+"),  # C/C++/Rust backtrace
    re.compile(r"^\s*by\s+0x[0-9a-fA-F]+"),  # Hex address reference
    re.compile(r"^\s*\[.*?\]\s+\.\.\."),  # Library elision
    re.compile(r"^\s*Called from:"),  # Called from marker
    re.compile(r"^\s*Caused by:"),  # Exception cause
    re.compile(r"^\s*---\s+Stack trace\s+---"),  # Stack trace header
    re.compile(r"^\s*堆栈跟踪"),  # Chinese "Stack trace"
    re.compile(r"^\s*调用堆栈"),  # Chinese "Call stack"
]

# Runtime/library path patterns to exclude from app-code frame preservation
_RUNTIME_PATH_PATTERNS = [
    re.compile(r"site-packages/"),
    re.compile(r"node_modules/"),
    re.compile(r"/usr/lib/"),
    re.compile(r"lib/python3\.\d+/"),
    re.compile(r"dist-packages/"),
    re.compile(r"__pycache__/"),
]


class GenericProcessor(Processor):
    """Fallback processor that applies universal compression heuristics."""

    priority = 999
    hook_patterns = []

    @property
    def name(self) -> str:
        return "generic"

    def can_handle(self, command: str) -> bool:
        return True  # Always matches as fallback

    def process(self, command: str, output: str, graph_ctx=None) -> str:
        lines = output.splitlines()
        lines = self._strip_ansi(lines)
        lines = self._strip_progress_bars(lines)
        lines = self._collapse_blank_lines(lines)
        lines = self._collapse_repeated_lines(lines)
        lines = self._collapse_similar_lines(lines)
        lines = self._collapse_similar_trailing(lines)
        lines = self._collapse_stack_traces(lines)
        lines = self._strip_trailing_whitespace(lines)
        
        # Compute sticky lines (high entropy) before truncation
        sticky = sticky_line_indices(lines)
        
        threshold = config.get("generic_truncate_threshold")
        if len(lines) > threshold:
            lines = self._truncate_middle(lines, sticky)
        return "\n".join(lines)

    def clean(self, text: str) -> str:
        """Light cleanup pass: ANSI strip and blank line collapse only.

        Used by the engine after a specialized processor to sanitize output
        without applying heavy dedup or truncation.
        """
        lines = text.splitlines()
        lines = self._strip_ansi(lines)
        lines = self._collapse_blank_lines(lines)
        lines = self._strip_trailing_whitespace(lines)
        return "\n".join(lines)

    def _strip_ansi(self, lines: list[str]) -> list[str]:
        return [ANSI_RE.sub("", line) for line in lines]

    def _strip_trailing_whitespace(self, lines: list[str]) -> list[str]:
        return [line.rstrip() for line in lines]

    def _strip_progress_bars(self, lines: list[str]) -> list[str]:
        """Remove lines that are purely progress bars or spinners."""
        result = []
        for line in lines:
            stripped = line.strip()
            # Unicode block bars: always progress noise.
            block = _PROGRESS_BLOCK_RE.search(stripped) if stripped else None
            if block and len(block.group(0)) > len(stripped) * 0.5:
                continue
            # ASCII bars (====, ####, ---->): only strip when accompanied by a
            # progress signal (%, [..], n/m, rate, ETA).  A bare "--------" or
            # "========" line is a separator/rule and must survive.
            ascii_bar = _ASCII_BAR_RE.search(stripped) if stripped else None
            if (
                ascii_bar
                and len(ascii_bar.group(0)) > len(stripped) * 0.5
                and _PROGRESS_CONTEXT_RE.search(stripped)
            ):
                continue
            # Spinner lines
            if stripped in (
                "⠋",
                "⠙",
                "⠹",
                "⠸",
                "⠼",
                "⠴",
                "⠦",
                "⠧",
                "⠇",
                "⠏",
                "⣾",
                "⣽",
                "⣻",
                "⢿",
                "⡿",
                "⣟",
                "⣯",
                "⣷",
            ):
                continue
            result.append(line)
        return result

    def _collapse_blank_lines(self, lines: list[str]) -> list[str]:
        """Merge consecutive blank lines into one."""
        result = []
        prev_blank = False
        for line in lines:
            is_blank = line.strip() == ""
            if is_blank and prev_blank:
                continue
            result.append(line)
            prev_blank = is_blank
        return result

    def _collapse_repeated_lines(self, lines: list[str]) -> list[str]:
        """Collapse consecutive identical lines into `line (xN)`."""
        if not lines:
            return lines
        result: list[str] = []
        current = lines[0]
        count = 1
        for line in lines[1:]:
            if line == current and current.strip():
                count += 1
            else:
                self._flush(result, current, count)
                current = line
                count = 1
        self._flush(result, current, count)
        return result

    def _collapse_similar_lines(self, lines: list[str]) -> list[str]:
        """Collapse consecutive lines that differ only in numbers/percentages.

        Only applies to lines where >=30% of the content is numeric — this
        targets progress output (curl, wget, download bars) while preserving
        data lines where numbers are meaningful identifiers.
        """
        if not lines:
            return lines
        result: list[str] = []
        current = lines[0]
        current_normalized = self._normalize_numbers(current)
        group: list[str] = [current]

        for line in lines[1:]:
            normalized = self._normalize_numbers(line)
            if (
                normalized == current_normalized
                and current.strip()
                and len(current.strip()) > 10
                and self._is_numeric_heavy(current)
            ):
                group.append(line)
            else:
                self._flush_similar(result, group)
                current = line
                current_normalized = normalized
                group = [line]

        self._flush_similar(result, group)
        return result

    def _normalize_numbers(self, line: str) -> str:
        """Replace all numbers with a placeholder for fuzzy comparison."""
        return _NUMERIC_RE.sub("N", line.strip())

    def _is_numeric_heavy(self, line: str) -> bool:
        """Check if a line is progress/status output where numbers are noise.

        Returns True for lines where numeric changes are not meaningful data,
        such as progress bars, download stats, and transfer indicators.
        """
        stripped = line.strip()
        if not stripped:
            return False
        # Only collapse on EXPLICIT progress/transfer signals.  Bare digit-ratio
        # heuristics are deliberately NOT used: they also match legitimate
        # numeric data tables (e.g. yearly metrics, id columns), whose rows are
        # meaningful and must be preserved rather than collapsed as redraw noise.
        # Percentage patterns
        if re.search(r"\d+(\.\d+)?%", stripped):
            return True
        # Transfer rate patterns
        if re.search(r"\d+(\.\d+)?\s*(KB|MB|GB|B|kB|MiB|GiB|k|M|G)/s", stripped):
            return True
        # ETA/time remaining patterns
        if re.search(r"(ETA|eta)\s+\d+", stripped):
            return True
        # Curl/wget progress format: lines with --:--:-- time patterns
        numeric_chars = sum(1 for c in stripped if c.isdigit())
        return bool(re.search(r"--:--:--|(\d+:){2}\d+", stripped) and numeric_chars >= 5)

    def _flush(self, result: list[str], line: str, count: int) -> None:
        if count > 1:
            result.append(f"{line} (x{count})")
        else:
            result.append(line)

    def _flush_similar(self, result: list[str], group: list[str]) -> None:
        count = len(group)
        if count >= 5:
            result.append(group[0])
            result.append(f"  ... ({count - 2} similar lines)")
            result.append(group[-1])
        else:
            result.extend(group)

    def _truncate_middle(self, lines: list[str], sticky: frozenset[int] | None = None) -> list[str]:
        """Truncate middle of long output, preserving sticky lines.
        
        When sticky lines are provided (high-entropy content), they are
        never truncated in the middle. They are extracted before truncation
        and re-interleaved at their original positions.
        """
        keep_head = config.get("generic_keep_head")
        keep_tail = config.get("generic_keep_tail")
        total = len(lines)
        
        # If we have sticky lines, use special handling
        if sticky and len(sticky) > 0:
            return self._truncate_with_sticky(lines, sticky, keep_head, keep_tail)
        
        # Standard truncation without sticky lines
        head = lines[:keep_head] if keep_head > 0 else []
        tail = lines[-keep_tail:] if keep_tail > 0 else []
        removed = total - len(head) - len(tail)
        if removed <= 0:
            return lines
        return [
            *head,
            f"... ({removed} lines truncated, {total} total) ...",
            *tail,
        ]

    def _truncate_with_sticky(
        self, lines: list[str], sticky: frozenset[int], keep_head: int, keep_tail: int
    ) -> list[str]:
        """Truncate while preserving sticky lines at their original positions."""
        total = len(lines)
        
        # Separate sticky and non-sticky lines
        sticky_lines = {}
        non_sticky_lines = []
        non_sticky_to_original = []  # Maps non-sticky index back to original index
        
        for idx, line in enumerate(lines):
            if idx in sticky:
                sticky_lines[idx] = line
            else:
                non_sticky_to_original.append(idx)
                non_sticky_lines.append(line)
        
        # Truncate non-sticky lines
        head_count = min(keep_head, len(non_sticky_lines))
        tail_count = min(keep_tail, len(non_sticky_lines) - head_count)
        
        if head_count + tail_count >= len(non_sticky_lines):
            # Not enough to truncate, return original
            return lines
        
        kept_non_sticky_indices = set(
            non_sticky_to_original[:head_count] + non_sticky_to_original[-tail_count:]
        )
        
        # Rebuild output, preserving sticky lines and keeping head/tail of non-sticky
        result: list[str] = []
        last_idx = -1
        
        for idx in range(total):
            if idx in sticky_lines:
                # Always keep sticky lines
                if idx > last_idx + 1 and result:
                    # Add truncation marker if there was a gap
                    gap_count = idx - last_idx - 1
                    if gap_count > 0:
                        result.append(f"... ({gap_count} lines omitted, sticky preserved) ...")
                result.append(sticky_lines[idx])
                last_idx = idx
            elif idx in kept_non_sticky_indices:
                # Keep this non-sticky line
                result.append(lines[idx])
                last_idx = idx
        
        return result

    def _collapse_similar_trailing(self, lines: list[str]) -> list[str]:
        """Collapse consecutive lines with similar trailing regions.
        
        Ported from headroom log_compressor.py::_dedupe_similar (L419–443).
        Splits each line on first ':' or '=', normalizes the trailing region
        (numbers → N, hex addresses → ADDR, paths → /PATH/), and collapses
        consecutive lines with identical normalized forms.
        
        Only applies to lines that contain a ':' or '=' separator — lines
        without a separator are left untouched (they don't have a meaningful
        trailing region to normalize).
        """
        if not lines:
            return lines
        
        result: list[str] = []
        current = lines[0]
        current_has_sep = self._has_separator(current)
        current_normalized = self._normalize_trailing_region(current) if current_has_sep else None
        count = 1
        
        for line in lines[1:]:
            line_has_sep = self._has_separator(line)
            normalized = self._normalize_trailing_region(line) if line_has_sep else None
            
            if (
                current_normalized is not None
                and normalized is not None
                and normalized == current_normalized
                and current.strip()
                and len(current.strip()) > 5
            ):
                count += 1
            else:
                self._flush(result, current, count)
                current = line
                current_has_sep = line_has_sep
                current_normalized = normalized
                count = 1
        
        self._flush(result, current, count)
        return result

    def _has_separator(self, line: str) -> bool:
        """Check if line contains a ':' or '=' separator."""
        return ":" in line or "=" in line

    def _normalize_trailing_region(self, line: str) -> str:
        r"""Normalize the trailing region of a line for deduplication.
        
        Splits on first ':' or '=', then normalizes the trailing portion:
        - Numbers → N
        - Hex addresses (0x...) → ADDR  
        - File paths (/[\w/]+/) → /PATH/
        
        Returns the original line unchanged if no separator is found.
        """
        # Split on first ':' or '='
        separator = None
        for sep in (":", "="):
            if sep in line:
                separator = sep
                break
        
        if separator is None:
            return line
        
        parts = line.split(separator, 1)
        prefix = parts[0] + separator
        trailing = parts[1] if len(parts) > 1 else ""
        
        # Normalize trailing region
        normalized = trailing
        
        # Replace numbers with N
        normalized = re.sub(r"\d+", "N", normalized)
        
        # Replace hex addresses with ADDR
        normalized = re.sub(r"0x[0-9a-fA-F]+", "ADDR", normalized)
        
        # Replace file paths with /PATH/
        normalized = re.sub(r"/[\w/]+/", "/PATH/", normalized)
        
        return prefix + normalized

    def _collapse_stack_traces(self, lines: list[str]) -> list[str]:
        """Detect and collapse stack traces, preserving app-code frames.
        
        Ported from headroom log_compressor.py stack trace logic.
        Keeps first 3 frames + app-code frames (paths NOT matching runtime patterns)
        up to 5 app frames, collapses remainder into "[... N runtime frames collapsed]".
        
        FIXED BEHAVIOR: Blank line inside a trace does NOT terminate it.
        Only a non-blank, non-matching, non-context line terminates the trace.
        Code context lines (indented snippets between File lines) are included
        as part of the trace block.
        """
        if not lines:
            return lines
        
        result: list[str] = []
        i = 0
        
        while i < len(lines):
            line = lines[i]
            
            # Check if this line matches a stack trace pattern
            if self._is_stack_trace_line(line):
                # Found start of a stack trace — collect the entire trace block
                trace_block: list[tuple[int, str]] = []  # (index, line)
                in_trace = True
                
                while i < len(lines) and in_trace:
                    current_line = lines[i]
                    
                    # Blank lines do NOT terminate traces (fixed from headroom bug)
                    if current_line.strip() == "":
                        trace_block.append((i, current_line))
                        i += 1
                        continue
                    
                    if self._is_stack_trace_line(current_line):
                        # Frame line (File "..." / at ... / Traceback etc.)
                        trace_block.append((i, current_line))
                        i += 1
                    elif current_line.startswith((" ", "\t")) and trace_block:
                        # Indented context line — part of the trace (code snippet,
                        # exception message continuation, etc.)
                        trace_block.append((i, current_line))
                        i += 1
                    else:
                        # Non-blank, non-matching, non-indented → terminates trace
                        in_trace = False
                
                # Identify which lines in the block are actual frame lines
                frame_indices = [
                    idx for idx, (_, line) in enumerate(trace_block)
                    if self._is_stack_trace_line(line)
                ]
                
                # Only collapse if there are more than 3 frame lines
                if len(frame_indices) > 3:
                    collapsed_trace = self._collapse_trace_frames(trace_block, frame_indices)
                    result.extend(collapsed_trace)
                else:
                    # Too short to collapse, keep as-is
                    result.extend(line for _, line in trace_block)
            else:
                result.append(line)
                i += 1
        
        return result

    def _is_stack_trace_line(self, line: str) -> bool:
        """Check if a line matches any stack trace pattern."""
        return any(pattern.search(line) for pattern in _STACK_TRACE_PATTERNS)

    def _collapse_trace_frames(
        self,
        block: list[tuple[int, str]],
        frame_indices: list[int],
    ) -> list[str]:
        """Collapse stack trace frames, preserving app-code frames and context.

        Keeps first 3 frames + up to 5 app-code frames (not in runtime paths).
        Collapses remaining runtime frames into a marker. Context lines
        (indented code snippets) are kept with their associated frame.

        Args:
            block: Full trace block as (original_index, line) tuples.
            frame_indices: Indices within block that are actual frame lines.
        """
        if len(frame_indices) <= 3:
            return [line for _, line in block]

        # Always keep first 3 frames (by position in frame_indices)
        keep_frames = set(frame_indices[:3])

        # Find app-code frames (not in runtime paths) among the remaining
        for fi in frame_indices[3:]:
            line = block[fi][1]
            if not self._is_runtime_frame(line):
                keep_frames.add(fi)

        # Keep up to 5 app-code frames total beyond the first 3
        app_beyond_head = [
            fi for fi in frame_indices[3:]
            if fi in keep_frames
        ]
        if len(app_beyond_head) > 5:
            # Only keep the first 5 app frames, drop the rest
            for fi in app_beyond_head[5:]:
                keep_frames.discard(fi)

        # Build the result, keeping frame lines + their trailing context lines
        result: list[str] = []
        last_kept_frame = -1

        for idx, (_, line) in enumerate(block):
            if idx in keep_frames:
                # Check for gap before this frame
                if last_kept_frame >= 0:
                    # Count how many frames were skipped
                    skipped_frames = [
                        f for f in frame_indices
                        if last_kept_frame < f < idx
                    ]
                    if skipped_frames:
                        result.append(
                            f"[... {len(skipped_frames)} runtime frames collapsed]"
                        )
                result.append(line)
                last_kept_frame = idx
            elif idx not in frame_indices and last_kept_frame >= 0:
                # Context line — keep it only if the preceding frame was kept
                # and it's not a blank line after a skipped frame
                if idx - 1 == last_kept_frame or (
                    idx - 1 >= 0 and idx - 1 in keep_frames
                ):
                    # Check that this is context for a kept frame
                    # Find the nearest preceding frame
                    nearest = max(
                        (f for f in frame_indices if f < idx),
                        default=-1,
                    )
                    if nearest in keep_frames:
                        result.append(line)

        # Final gap check: frames after the last kept frame
        trailing_frames = [
            f for f in frame_indices if f > last_kept_frame
        ]
        if trailing_frames:
            result.append(
                f"[... {len(trailing_frames)} runtime frames collapsed]"
            )

        return result

    def _is_runtime_frame(self, line: str) -> bool:
        """Check if a stack frame is from runtime/library code."""
        return any(pattern.search(line) for pattern in _RUNTIME_PATH_PATTERNS)
