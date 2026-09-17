"""Regressions for native grep payloads captured at the Kilo bridge boundary."""

import pytest

from src import config
from src.engine import CompressionEngine
from src.processors.search import SearchProcessor


LIMIT_NOTICE = "100 matches limit reached. Use limit=200 for more, or refine pattern."


def native_output(header="Found 100 matches", footer="", path="src/demo.py"):
    lines = [header, f"{path}:"]
    for number in range(1, 101):
        lines.extend([f"  Line {number}: assert value_{number} == {number}", ""])
    if footer:
        lines.extend(["", footer])
    return "\n".join(lines)


@pytest.fixture(params=["processor", "engine"])
def compress(request, monkeypatch):
    # Independent of the developer's personal compression settings.
    monkeypatch.setattr(config, "_config", dict(config._DEFAULTS))
    if request.param == "processor":
        return lambda command, output: SearchProcessor().process(command, output)
    return lambda command, output: CompressionEngine().compress(command, output)[0]


@pytest.mark.parametrize("limit", [5, 20, 100])
def test_captured_native_limit_format(compress, limit):
    footer = f"{limit} matches limit reached. Use limit={limit * 2} for more, or refine pattern."
    lines = [f"Found {limit} matches (more matches available)", "src/demo.py:"]
    for number in range(1, limit + 1):
        lines.extend([f"  Line {number}: assert value_{number} == {number}", ""])
    lines.extend(["", footer])
    raw = "\n".join(lines)
    result = compress("grep assert src/demo.py", raw)

    for number in range(1, 4):
        assert f"Line {number}: assert value_{number} == {number}" in result
    assert "more matches available" in result
    assert footer in result
    if limit >= 20:
        assert result.startswith(f"{limit} matches across 1 files:")
        assert f"... ({limit - 3} more)" in result


@pytest.mark.parametrize(
    "extra",
    [
        "100 matches limit reached. Use limit=200 for more, or refine pattern.",
        "Warning: some files could not be searched",
        "  [context] Line 101: context must not disappear",
        "  [match] Line 101: explicitly labelled match",
    ],
)
def test_unknown_or_context_native_output_is_preserved(compress, extra):
    raw = native_output(footer=extra)
    result = compress("grep assert src/demo.py", raw)
    assert extra in result
    assert "Line 1: assert value_1 == 1" in result
    if extra != LIMIT_NOTICE:
        assert result == raw


def test_captured_context_format_is_passed_through(compress):
    lines = ["Found 5 matches (more matches available)", "src/demo.py:"]
    for number in range(1, 6):
        lines.extend(
            [
                f"  [context] Line {number * 2}: before_{number}", "",
                f"  [match] Line {number * 2 + 1}: assert value_{number}", "",
            ],
        )
    lines.append("5 matches limit reached. Use limit=10 for more, or refine pattern.")
    raw = "\n".join(lines)
    assert compress("grep assert src/demo.py", raw) == raw


@pytest.mark.parametrize(
    "header",
    [
        "Found 100 matches (new status annotation)",
        "Found 100 matches in 1 file",
        "Found 100 matches across 1 file:",
    ],
)
def test_native_header_variants_never_drop_match_text(compress, header):
    raw = native_output(header=header)
    result = compress("grep assert src/demo.py", raw)
    assert "Line 1: assert value_1 == 1" in result
    if "new status annotation" in header:
        assert result == raw


@pytest.mark.parametrize(
    "path",
    [
        "dir with spaces/[a+b]_$file.py", "src/naïve-Ω.py",
        r"C:\work\demo.py", "bin/no-extension", "src/colon:name.py",
    ],
)
def test_limited_native_output_with_special_paths(compress, path):
    raw = native_output("Found 100 matches (more matches available)", LIMIT_NOTICE, path)
    result = compress("grep assert .", raw)
    assert path in result
    assert "Line 1: assert value_1 == 1" in result
    assert LIMIT_NOTICE in result


@pytest.mark.parametrize("command", ["grep fd src/demo.py", "rg fdfind src/demo.py"])
def test_search_terms_do_not_select_fd_processor(compress, command):
    raw = native_output()
    result = compress(command, raw)
    assert "100 matches across 1 files" in result
    assert "Line 1: assert value_1 == 1" in result


@pytest.mark.parametrize("file_count", [1, 31])
def test_mixed_cli_output_does_not_drop_unparsed_lines(compress, file_count):
    raw = "\n".join(
        [f"src/file_{i % file_count}.py:{i + 1}:match_{i}" for i in range(40)]
        + ["src/file with spaces.py:7:important unmatched format"]
    )
    assert compress("rg match src", raw) == raw


def test_inconsistent_native_count_is_preserved(compress):
    raw = native_output(header="Found 101 matches")
    assert compress("grep assert src/demo.py", raw) == raw


@pytest.mark.parametrize("file_count", [2, 31])
def test_native_multi_file_counts_and_limit_notice(compress, file_count):
    count = file_count * 10
    lines = [f"Found {count} matches (more matches available)"]
    for file in range(file_count):
        lines.append(f"src/file_{file}.py:")
        for number in range(1, 11):
            lines.extend([f"  Line {number}: file_{file}_match_{number}", ""])
    notice = f"{count} matches limit reached. Use limit={count * 2} for more, or refine pattern."
    lines.append(notice)
    result = compress("grep match src", "\n".join(lines))
    assert result.startswith(f"{count} matches across {file_count} files")
    assert "Line 1: file_0_match_1" in result
    assert "Line 1: file_1_match_1" in result
    assert notice in result


def test_limited_native_match_text_is_literal(compress):
    literal = r"[](){}.*+?$^\|: 'quoted' café" + "\tΩ"
    raw = native_output("Found 100 matches (more matches available)", LIMIT_NOTICE)
    raw = raw.replace("assert value_1 == 1", literal)
    result = compress("grep '[](){}.*+?$^' .", raw)
    assert f"Line 1: {literal}" in result
    assert LIMIT_NOTICE in result
