"""Tests for the Claude Code PostToolUse hook (scripts/hook_posttool.py).

Payload shapes mirror real Claude Code 2.1 ``tool_response`` objects; the hook
must return a copy of that shape with only its text fields replaced, because
Claude Code rejects an ``updatedToolOutput`` that does not match the tool.
"""

import json
import os
import sqlite3
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(REPO_ROOT, "scripts", "hook_posttool.py")
METRICS = os.path.join(REPO_ROOT, "src", "graphify_metrics.py")


@pytest.fixture
def home(tmp_path, monkeypatch):
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    return home_dir


def _run_hook(payload, home_dir):
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(  # noqa: S603
        [sys.executable, HOOK],
        input=raw,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={**os.environ, "HOME": str(home_dir)},
    )


def _query_db(home_dir, sql):
    """Read the hook subprocess's savings DB directly.

    SavingsTracker caches its DB path class-wide, so an in-process tracker could
    point at another test's database.
    """
    conn = sqlite3.connect(home_dir / ".token-saver" / "savings.db")
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def _updated(result):
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    hso = data["hookSpecificOutput"]
    assert hso["hookEventName"] == "PostToolUse"
    return hso["updatedToolOutput"]


def _passthrough(result):
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def _bash_payload(command, stdout, stderr="", **extra):
    return {
        "hook_event_name": "PostToolUse",
        "session_id": "claude-session-1",
        "cwd": extra.pop("cwd", REPO_ROOT),
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {
            "stdout": stdout,
            "stderr": stderr,
            "interrupted": False,
            "isImage": False,
            "noOutputExpected": False,
            **extra,
        },
    }


def _read_payload(path, content, **tool_input):
    lines = content.count("\n") + 1
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": path, **tool_input},
        "tool_response": {
            "type": "text",
            "file": {
                "filePath": path,
                "content": content,
                "numLines": lines,
                "startLine": 1,
                "totalLines": lines,
            },
        },
    }


GIT_STATUS = "\n".join(f" M src/file{i}.py" for i in range(200))
LOG_CONTENT = "\n".join(f"2026-01-01 12:00:{i % 60:02d} INFO request {i} ok" for i in range(800))


class TestBash:
    def test_compresses_and_keeps_response_shape(self, home):
        result = _run_hook(_bash_payload("git status", GIT_STATUS), home)
        updated = _updated(result)
        assert set(updated) == {"stdout", "stderr", "interrupted", "isImage", "noOutputExpected"}
        assert len(updated["stdout"]) < len(GIT_STATUS)
        assert updated["stderr"] == ""
        assert updated["interrupted"] is False

    def test_merges_stderr_into_compressed_stdout(self, home):
        result = _run_hook(_bash_payload("git status", GIT_STATUS, "warning: noisy"), home)
        updated = _updated(result)
        assert updated["stderr"] == ""

    def test_unsupported_command_passes_through(self, home):
        _passthrough(_run_hook(_bash_payload("echo hello", "hello\n" * 100), home))

    def test_excluded_command_passes_through(self, home):
        _passthrough(_run_hook(_bash_payload("sudo git status", GIT_STATUS), home))

    def test_image_output_passes_through(self, home):
        payload = _bash_payload("git status", GIT_STATUS)
        payload["tool_response"]["isImage"] = True
        _passthrough(_run_hook(payload, home))

    def test_records_saving_under_claude_platform(self, home):
        _updated(_run_hook(_bash_payload("git status", GIT_STATUS), home))
        rows = _query_db(home, "SELECT platform, command FROM savings")
        assert ("claude_code", "git status") in rows


class TestRead:
    def test_compresses_large_log_and_updates_line_count(self, home):
        updated = _updated(_run_hook(_read_payload("/x/app.log", LOG_CONTENT), home))
        assert updated["type"] == "text"
        file_info = updated["file"]
        assert file_info["filePath"] == "/x/app.log"
        assert len(file_info["content"]) < len(LOG_CONTENT)
        assert file_info["numLines"] == len(file_info["content"].splitlines())
        assert file_info["startLine"] == 1

    @pytest.mark.parametrize(
        "path",
        ["/x/main.py", "/x/Main.qml", "/x/CMakeLists.txt", "/x/FindFoo.cmake", "/x/view.cpp"],
    )
    def test_source_files_are_never_compressed(self, home, path):
        content = "\n".join(f"line {i} = value_{i}" for i in range(900))
        _passthrough(_run_hook(_read_payload(path, content), home))

    def test_ranged_read_passes_through(self, home):
        _passthrough(_run_hook(_read_payload("/x/app.log", LOG_CONTENT, offset=10), home))
        _passthrough(_run_hook(_read_payload("/x/app.log", LOG_CONTENT, limit=900), home))

    def test_non_text_read_passes_through(self, home):
        payload = _read_payload("/x/app.log", LOG_CONTENT)
        payload["tool_response"]["type"] = "image"
        _passthrough(_run_hook(payload, home))


class TestGrepAndGlob:
    def test_grep_content_mode(self, home):
        content = "\n".join(f"src/f{i % 5}.py:{i}:    assert value_{i} == {i}" for i in range(300))
        payload = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "assert", "path": "/x", "output_mode": "content"},
            "tool_response": {
                "mode": "content",
                "numFiles": 0,
                "filenames": [],
                "content": content,
                "numLines": 300,
                "totalLines": 300,
            },
        }
        updated = _updated(_run_hook(payload, home))
        assert updated["mode"] == "content"
        assert updated["filenames"] == []
        assert updated["totalLines"] == 300
        assert updated["content"].startswith("300 matches across 5 files:")
        assert updated["numLines"] == len(updated["content"].splitlines())

    def test_grep_files_mode_keeps_true_count(self, home):
        filenames = [f"src/pkg{i % 7}/mod{i}.py" for i in range(400)]
        payload = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "assert", "path": "/x"},
            "tool_response": {
                "mode": "files_with_matches",
                "filenames": filenames,
                "numFiles": 400,
                "totalFiles": 400,
            },
        }
        updated = _updated(_run_hook(payload, home))
        assert isinstance(updated["filenames"], list)
        assert all(isinstance(name, str) for name in updated["filenames"])
        assert len(updated["filenames"]) < len(filenames)
        assert updated["numFiles"] == 400

    def test_glob_filenames(self, home):
        payload = {
            "tool_name": "Glob",
            "tool_input": {"pattern": "**/*.py", "path": "/x"},
            "tool_response": {
                "filenames": [f"src/pkg{i % 7}/mod{i}.py" for i in range(400)],
                "durationMs": 4,
                "numFiles": 400,
                "truncated": False,
            },
        }
        updated = _updated(_run_hook(payload, home))
        assert set(updated) == {"filenames", "durationMs", "numFiles", "truncated"}
        assert updated["filenames"][0] == "400 files found:"
        assert updated["numFiles"] == 400

    def test_small_glob_passes_through(self, home):
        payload = {
            "tool_name": "Glob",
            "tool_input": {"pattern": "*.txt"},
            "tool_response": {"filenames": ["a.txt", "b.txt"], "numFiles": 2, "truncated": False},
        }
        _passthrough(_run_hook(payload, home))


class TestOtherTools:
    def test_async_agent_launch_passes_through(self, home):
        payload = {
            "tool_name": "Agent",
            "tool_input": {"description": "survey"},
            "tool_response": {"isAsync": True, "status": "async_launched", "agentId": "a1"},
        }
        _passthrough(_run_hook(payload, home))

    def test_agent_adapter_rebuilds_text_blocks(self):
        sys.path.insert(0, REPO_ROOT)
        from scripts.hook_posttool import _agent

        response = {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}
        tool, command, output, apply = _agent({"description": "survey"}, response)
        assert (tool, command, output) == ("task", "task survey", "a\nb")
        assert apply("short") == {"content": [{"type": "text", "text": "short"}]}
        assert response["content"][0]["text"] == "a"  # original untouched

    def test_webfetch_adapter_targets_result(self):
        sys.path.insert(0, REPO_ROOT)
        from scripts.hook_posttool import _webfetch

        response = {"bytes": 5, "code": 200, "codeText": "OK", "result": "page", "url": "u"}
        tool, command, output, apply = _webfetch({"url": "https://e.com"}, response)
        assert (tool, command, output) == ("webfetch", "curl https://e.com", "page")
        assert apply("p") == {**response, "result": "p"}

    def test_unhandled_tool_passes_through(self, home):
        payload = {"tool_name": "Edit", "tool_input": {}, "tool_response": {"filePath": "x"}}
        _passthrough(_run_hook(payload, home))

    def test_malformed_payload_fails_open(self, home):
        _passthrough(_run_hook("not-json", home))
        _passthrough(_run_hook(json.dumps(["list"]), home))
        _passthrough(_run_hook({"tool_name": "Bash", "tool_input": "x"}, home))


class TestGraphifyIntegration:
    @staticmethod
    def _project(tmp_path):
        project = tmp_path / "proj"
        (project / "graphify-out").mkdir(parents=True)
        (project / "graphify-out" / "GRAPH_REPORT.md").write_text(
            "# Report\n- 42 files · ~150,000 words\n", encoding="utf-8"
        )
        return project

    @staticmethod
    def _graphify_rows(home_dir):
        db = home_dir / ".token-saver" / "savings.db"
        if not db.exists():
            return []
        return _query_db(
            home_dir, "SELECT session_id, project, question, saved_tokens FROM graphify_savings"
        )

    def test_records_graphify_query(self, home, tmp_path):
        project = self._project(tmp_path)
        output = "NODE foo -> bar (src/foo.cpp:12)\n" * 20
        payload = _bash_payload('graphify query "what calls foo"', output, cwd=str(project))
        _run_hook(payload, home)
        ((session, recorded_project, question, saved),) = self._graphify_rows(home)
        assert session == "claude-session-1"
        assert recorded_project == str(project.resolve())
        assert question == "what calls foo"
        assert saved > 0

    def test_records_graphify_query_after_cd(self, home, tmp_path):
        project = self._project(tmp_path)
        output = "NODE foo -> bar (src/foo.cpp:12)\n" * 20
        payload = _bash_payload(
            "cd proj && graphify query 'what calls foo'", output, cwd=str(tmp_path)
        )
        _run_hook(payload, home)
        ((_, recorded_project, question, _),) = self._graphify_rows(home)
        assert recorded_project == str(project.resolve())
        assert question == "what calls foo"

    def test_records_graphify_query_with_post_cd_cwd(self, home, tmp_path):
        """Claude reports the shell's cwd after the command, i.e. after the cd."""
        project = self._project(tmp_path)
        output = "NODE foo -> bar (src/foo.cpp:12)\n" * 20
        payload = _bash_payload(
            "cd proj && graphify query 'what calls foo'", output, cwd=str(project)
        )
        _run_hook(payload, home)
        ((_, recorded_project, _, _),) = self._graphify_rows(home)
        assert recorded_project == str(project.resolve())

    def test_query_without_graph_report_not_recorded(self, home, tmp_path):
        payload = _bash_payload('graphify query "q"', "NODE x\n" * 20, cwd=str(tmp_path))
        _run_hook(payload, home)
        assert self._graphify_rows(home) == []

    def test_non_query_graphify_command_not_recorded(self, home, tmp_path):
        project = self._project(tmp_path)
        _run_hook(_bash_payload("graphify update .", "done\n", cwd=str(project)), home)
        assert self._graphify_rows(home) == []

    def test_metrics_module_runs_as_script(self, home, tmp_path):
        """The Kilo plugin invokes graphify_metrics.py directly as a script."""
        project = self._project(tmp_path)
        event = {"project": str(project), "question": "q", "output": "x" * 400}
        result = subprocess.run(  # noqa: S603
            [sys.executable, METRICS],
            input=json.dumps(event),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            env={**os.environ, "HOME": str(home)},
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["recorded"] is True


class TestParseQueryCommand:
    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ('graphify query "how does auth work"', ("how does auth work", None)),
            ("graphify query 'x y'", ("x y", None)),
            ('/usr/bin/graphify query "q" --budget 2000', ("q", None)),
            ('cd src/sonicde/kwin && graphify query "q"', ("q", "src/sonicde/kwin")),
            ("graphify update .", None),
            ("graphify query --help", None),
            ("git status", None),
            ('graphify query "unterminated', None),
        ],
    )
    def test_parse(self, command, expected):
        sys.path.insert(0, REPO_ROOT)
        from src.graphify_metrics import parse_query_command

        assert parse_query_command(command) == expected


class TestHooksManifest:
    def test_posttool_matcher_covers_adapters(self):
        sys.path.insert(0, REPO_ROOT)
        from scripts.hook_posttool import _ADAPTERS

        with open(os.path.join(REPO_ROOT, "hooks", "hooks.json")) as f:
            hooks = json.load(f)["hooks"]
        assert "PreToolUse" not in hooks  # no command rewriting / permission bypass
        (entry,) = hooks["PostToolUse"]
        assert set(entry["matcher"].split("|")) == set(_ADAPTERS)
        assert "hook_posttool.py" in entry["hooks"][0]["command"]
        assert entry["hooks"][0]["timeout"] <= 60  # seconds, not milliseconds
