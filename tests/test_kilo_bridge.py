"""Integration tests for the Kilo post-tool compression bridge."""

import json
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.path.join(REPO_ROOT, "kilo", "compress.py")


def _run_bridge(payload):
    return subprocess.run(  # noqa: S603
        [sys.executable, BRIDGE],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


class TestKiloBridge:
    def test_native_grep_limit_payload_preserves_matches(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        lines = ["Found 100 matches (more matches available)", "src/demo.py:"]
        for number in range(1, 101):
            lines.extend([f"  Line {number}: assert value_{number} == {number}", ""])
        notice = "100 matches limit reached. Use limit=200 for more, or refine pattern."
        lines.extend(["", notice])
        raw = "\n".join(lines)
        result = _run_bridge({"tool": "grep", "command": "grep assert src/demo.py", "output": raw})
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["compressed"] is True
        assert data["stats"]["processor"] == "search"
        assert data["stats"]["originalChars"] == len(raw)
        assert data["output"].startswith("100 matches across 1 files:")
        assert "Line 1: assert value_1 == 1" in data["output"]
        assert "Line 3: assert value_3 == 3" in data["output"]
        assert "... (97 more)" in data["output"]
        assert notice in data["output"]

        # The live hook fired twice. Reprocessing must not erase the first pass.
        second = _run_bridge(
            {"tool": "grep", "command": "grep assert src/demo.py", "output": data["output"]},
        )
        assert json.loads(second.stdout) == {"compressed": False}

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
        result = subprocess.run(  # noqa: S603
            [sys.executable, BRIDGE],
            input="not-json",
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

        assert result.returncode == 0
        assert json.loads(result.stdout) == {"compressed": False}
