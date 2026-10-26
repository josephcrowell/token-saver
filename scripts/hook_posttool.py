#!/usr/bin/env python3
"""PostToolUse hook for Claude Code.

Mirrors the Kilo Code plugin: compresses output that a tool has already
produced instead of rewriting the command before it runs, so commands execute
exactly once, unmodified, under Claude Code's own permission rules.  Replaces
the output via ``hookSpecificOutput.updatedToolOutput``, which Claude Code
validates against each tool's output shape — so every adapter below returns a
copy of ``tool_response`` with only its text fields swapped.

Also records Graphify context-reduction metrics for ``graphify query`` Bash
commands, like the Kilo plugin does.
"""

import copy
import json
import logging
import os
import sys

# Ensure the extension root is importable (scripts/ -> plugin root)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_log = logging.getLogger("token-saver.hook_posttool")
_log.setLevel(logging.DEBUG)
_debug = os.environ.get("TOKEN_SAVER_DEBUG", "").lower() in ("1", "true", "yes")
if _debug:
    from src import data_dir as _data_dir

    _log_dir = _data_dir()
    os.makedirs(_log_dir, exist_ok=True)
    _handler = logging.FileHandler(os.path.join(_log_dir, "hook.log"))
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))
    _log.addHandler(_handler)
else:
    _log.addHandler(logging.NullHandler())

_PLATFORM = "claude_code"


def _join_lines(lines: list) -> str:
    return "\n".join(str(line) for line in lines)


# --- Per-tool adapters ----------------------------------------------------
# Each takes (tool_input, tool_response) and returns
# (engine_tool, command, output, apply) or None when there is nothing to do.
# ``apply(compressed)`` builds the replacement tool_response.


def _bash(tool_input, response):
    command = tool_input.get("command")
    if not isinstance(command, str) or response.get("isImage"):
        return None
    stdout = response.get("stdout") or ""
    stderr = response.get("stderr") or ""
    if not isinstance(stdout, str) or not isinstance(stderr, str):
        return None
    output = f"{stdout}\n{stderr}" if stdout and stderr else stdout or stderr

    def apply(compressed):
        new = copy.deepcopy(response)
        new["stdout"] = compressed
        new["stderr"] = ""
        return new

    return "bash", command, output, apply


def _read(tool_input, response):
    # Ranged reads (offset/limit) are deliberate slices: never second-guess them.
    if tool_input.get("offset") is not None or tool_input.get("limit") is not None:
        return None
    file_info = response.get("file")
    if response.get("type") != "text" or not isinstance(file_info, dict):
        return None
    content = file_info.get("content")
    path = file_info.get("filePath") or tool_input.get("file_path") or ""
    if not isinstance(content, str):
        return None

    def apply(compressed):
        new = copy.deepcopy(response)
        new["file"]["content"] = compressed
        new["file"]["numLines"] = len(compressed.splitlines())
        return new

    return "read", f"cat {path}", content, apply


def _grep(tool_input, response):
    pattern = tool_input.get("pattern", "")
    path = tool_input.get("path") or tool_input.get("glob") or ""
    command = f"grep {pattern} {path}".rstrip()
    content = response.get("content")
    if isinstance(content, str) and content:

        def apply(compressed):
            new = copy.deepcopy(response)
            new["content"] = compressed
            if "numLines" in new:
                new["numLines"] = len(compressed.splitlines())
            return new

        return "grep", command, content, apply
    return _filename_list("grep", f"grep -l {pattern} {path}".rstrip(), response)


def _glob(tool_input, response):
    command = f"find {tool_input.get('path') or '.'} -name {tool_input.get('pattern', '')}"
    return _filename_list("glob", command, response)


def _filename_list(tool, command, response):
    """Compress a ``filenames`` array; counts stay the true totals."""
    filenames = response.get("filenames")
    if not isinstance(filenames, list) or not filenames:
        return None

    def apply(compressed):
        new = copy.deepcopy(response)
        new["filenames"] = compressed.splitlines()
        return new

    return tool, command, _join_lines(filenames), apply


def _agent(tool_input, response):
    blocks = response.get("content")
    if not isinstance(blocks, list) or not blocks:
        return None  # async launches carry no result yet
    if not all(isinstance(b, dict) and b.get("type") == "text" for b in blocks):
        return None
    text = "\n".join(str(b.get("text", "")) for b in blocks)
    description = tool_input.get("description") or tool_input.get("subagent_type") or ""

    def apply(compressed):
        new = copy.deepcopy(response)
        new["content"] = [{"type": "text", "text": compressed}]
        return new

    return "task", f"task {description}", text, apply


def _webfetch(tool_input, response):
    result = response.get("result")
    if not isinstance(result, str):
        return None

    def apply(compressed):
        new = copy.deepcopy(response)
        new["result"] = compressed
        return new

    return "webfetch", f"curl {tool_input.get('url', '')}", result, apply


_ADAPTERS = {
    "Bash": _bash,
    "Read": _read,
    "Grep": _grep,
    "Glob": _glob,
    "Agent": _agent,
    "Task": _agent,
    "WebFetch": _webfetch,
}


def _record_graphify(command, output, cwd, session_id):
    """Record Graphify query metrics for ``graphify query`` commands (best effort)."""
    from src import graphify_metrics  # noqa: PLC0415

    parsed = graphify_metrics.parse_query_command(command)
    if parsed is None or not output:
        return
    question, cd_dir = parsed
    cwd = cwd or os.getcwd()
    # Claude Code's Bash keeps its working directory between calls, so the
    # payload cwd may already be the post-``cd`` directory.
    candidates = [os.path.join(cwd, os.path.expanduser(cd_dir)), cwd] if cd_dir else [cwd]
    for project in candidates:
        if os.path.isfile(os.path.join(project, "graphify-out", "GRAPH_REPORT.md")):
            graphify_metrics.record_query(project, question, output, session_id or None)
            return


def build_response(input_data: dict) -> dict | None:
    """Return the hook's JSON reply for a PostToolUse payload, or None to pass through."""
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input")
    response = input_data.get("tool_response")
    adapter = _ADAPTERS.get(tool_name)
    if adapter is None or not isinstance(tool_input, dict) or not isinstance(response, dict):
        return None

    adapted = adapter(tool_input, response)
    if adapted is None:
        return None
    tool, command, output, apply = adapted
    session_id = input_data.get("session_id") or None

    if tool == "bash":
        try:
            _record_graphify(command, output, input_data.get("cwd"), session_id)
        except Exception:
            _log.exception("Graphify metrics failed for %r", command[:200])

    from src import core  # noqa: PLC0415

    result = core.compress_tool_output(
        command, output, tool=tool, platform=_PLATFORM, session_id=session_id
    )
    if result is None:
        _log.debug("Not compressed: tool=%s command=%r", tool_name, command[:200])
        return None
    _log.debug(
        "Compressed: tool=%s processor=%s %d -> %d",
        tool_name,
        result.processor,
        result.original_len,
        result.compressed_len,
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "updatedToolOutput": apply(result.compressed),
        }
    }


def main():
    try:
        input_data = json.loads(sys.stdin.read())
        reply = build_response(input_data) if isinstance(input_data, dict) else None
    except Exception:
        # Fail open: an integration error must never hide or break tool output.
        _log.exception("PostToolUse hook failed")
        reply = None
    if reply is not None:
        json.dump(reply, sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
