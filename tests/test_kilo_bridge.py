"""Integration tests for the Kilo post-tool compression bridge."""

import json
import os
import subprocess
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.path.join(REPO_ROOT, "kilo", "compress.py")


def _run_bridge(payload):
    return subprocess.run(
        [sys.executable, BRIDGE],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


class TestKiloBridge:
    def test_compresses_supported_command_output(self):
        output = "\n".join(
            [
                " M src/file.py",
                " M src/file.py",
                " M src/file.py",
                " M src/file.py",
            ]
            * 40
        )
        result = _run_bridge(
            {
                "command": "git status",
                "output": output,
                "session_id": "kilo-session-1",
            }
        )

        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["compressed"] is True
        assert len(data["output"]) < len(output)
        assert data["stats"]["originalChars"] == len(output)

    def test_unsupported_command_passes_through(self):
        result = _run_bridge({"command": "echo hello", "output": "hello\n" * 100})

        assert result.returncode == 0
        assert json.loads(result.stdout) == {"compressed": False}

    def test_malformed_payload_fails_open(self):
        result = subprocess.run(
            [sys.executable, BRIDGE],
            input="not-json",
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

        assert result.returncode == 0
        assert json.loads(result.stdout) == {"compressed": False}
