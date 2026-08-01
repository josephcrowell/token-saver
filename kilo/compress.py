#!/usr/bin/env python3
"""JSON bridge used by the Kilo Code plugin's post-tool hook."""

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
        if not isinstance(command, str) or not isinstance(output, str):
            return
        if not output or not core.should_compress(command):
            json.dump({"compressed": False}, sys.stdout)
            return

        if session_id:
            os.environ["TOKEN_SAVER_SESSION"] = str(session_id)
        result = core.compress(command, output)
        if not result.was_compressed:
            json.dump({"compressed": False}, sys.stdout)
            return

        core.record_result(result, command, "kilo_code")
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
