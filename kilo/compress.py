#!/usr/bin/env python3
"""JSON bridge used by the Kilo Code plugin's post-tool hook.

Handles both bash/shell commands and non-bash Kilo tools (read, grep, glob,
webfetch, task, etc.).  For non-bash tools the caller passes a ``tool`` field
and a synthetic ``command`` string that maps to the appropriate processor.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import core


def main():
    try:
        data = json.load(sys.stdin)
        command = data.get("command", "")
        output = data.get("output", "")
        session_id = data.get("session_id", "")
        tool = data.get("tool", "")
        if not isinstance(command, str) or not isinstance(output, str):
            return

        # For bash commands, use should_compress gate (excludes sudo, editors,
        # complex pipes, etc.).  For non-bash tools, skip the gate — the
        # engine's min_input_length check filters out short outputs.
        result = core.compress_tool_output(
            command, output, tool=tool, platform="kilo_code", session_id=session_id
        )
        if result is None:
            json.dump({"compressed": False}, sys.stdout)
            return

        json.dump(
            {
                "compressed": True,
                "output": result.compressed,
                "stats": {
                    "processor": result.processor,
                    "originalChars": result.original_len,
                    "compressedChars": result.compressed_len,
                },
            },
            sys.stdout,
        )
    except Exception:
        # Fail open: an integration error must never hide or break tool output.
        json.dump({"compressed": False}, sys.stdout)


if __name__ == "__main__":
    main()
