"""Tests for version check module: comparison, fail-open."""

import io
import json
import os
import sys
import time
import urllib.error

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.version_check as version_check
from src.version_check import (
    _parse_version,
    _read_cache,
    _write_cache,
    check_for_update,
)


class TestParseVersion:
    def test_simple(self):
        assert _parse_version("1.0.0") == (1, 0, 0)

    def test_with_v_prefix(self):
        assert _parse_version("v2.3.4") == (2, 3, 4)

    def test_with_whitespace(self):
        assert _parse_version("  1.2.3  ") == (1, 2, 3)

    def test_comparison(self):
        assert _parse_version("1.2.0") > _parse_version("1.1.9")
        assert _parse_version("2.0.0") > _parse_version("1.99.99")
        assert _parse_version("1.0.0") == _parse_version("v1.0.0")

    def test_prerelease_suffix_stripped(self):
        assert _parse_version("1.0.0-beta") == (1, 0, 0)
        assert _parse_version("2.1.0-rc.1") == (2, 1, 0)
        assert _parse_version("v1.2.3-alpha") == (1, 2, 3)


class TestCheckForUpdate:
    def test_update_available(self):
        result = check_for_update(fetch_fn=lambda: "99.0.0")
        assert result is not None
        assert "99.0.0" in result
        assert "token-saver update" in result

    def test_already_up_to_date(self):
        from src import __version__

        result = check_for_update(fetch_fn=lambda: __version__)
        assert result is None

    def test_older_remote_version(self):
        result = check_for_update(fetch_fn=lambda: "0.0.1")
        assert result is None

    def test_fail_open_on_fetch_error(self):
        def failing_fetch():
            raise ConnectionError("Network down")

        result = check_for_update(fetch_fn=failing_fetch)
        assert result is None

    def test_fail_open_on_bad_version(self):
        def bad_version_fetch():
            return "not-a-version"

        result = check_for_update(fetch_fn=bad_version_fetch)
        assert result is None

    def test_fail_open_on_empty_version(self):
        result = check_for_update(fetch_fn=lambda: "")
        assert result is None

    def test_fail_open_on_none_version(self):
        def none_fetch():
            return None

        result = check_for_update(fetch_fn=none_fetch)
        assert result is None


class TestVersionCache:
    def test_write_then_read_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr(version_check, "_cache_path", lambda: str(tmp_path / "cache.json"))
        _write_cache("9.9.9")
        assert _read_cache(ttl=3600) == "9.9.9"

    def test_read_expired_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(version_check, "_cache_path", lambda: str(tmp_path / "cache.json"))
        _write_cache("9.9.9")
        # ttl=0 means anything written in the past is already stale
        assert _read_cache(ttl=0) is None

    def test_read_missing_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(version_check, "_cache_path", lambda: str(tmp_path / "nope.json"))
        assert _read_cache(ttl=3600) is None

    def test_fresh_cache_skips_network(self, tmp_path, monkeypatch):
        monkeypatch.setattr(version_check, "_cache_path", lambda: str(tmp_path / "cache.json"))
        _write_cache("99.0.0")

        def fail_fetch(*_a, **_k):
            raise AssertionError("network should not be hit when cache is fresh")

        monkeypatch.setattr(version_check, "_fetch_latest_version", fail_fetch)
        result = check_for_update()
        assert result is not None
        assert "99.0.0" in result

    def test_miss_fetches_and_populates_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr(version_check, "_cache_path", lambda: str(tmp_path / "cache.json"))
        calls = []

        def counting_fetch(*_a, **_k):
            calls.append(1)
            return "99.0.0"

        monkeypatch.setattr(version_check, "_fetch_latest_version", counting_fetch)
        check_for_update()
        check_for_update()  # second call should read the cache, not refetch
        assert len(calls) == 1
        assert _read_cache(ttl=3600) == "99.0.0"

    def test_fetch_fn_override_bypasses_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr(version_check, "_cache_path", lambda: str(tmp_path / "cache.json"))
        _write_cache("0.0.1")  # stale-but-present cache
        # fetch_fn path must ignore the cache entirely
        result = check_for_update(fetch_fn=lambda: "99.0.0")
        assert result is not None
        assert "99.0.0" in result

    def test_cache_from_another_repo_is_ignored(self, tmp_path, monkeypatch):
        """A lookup cached against upstream must not drive this fork's banner."""
        cache = tmp_path / "cache.json"
        monkeypatch.setattr(version_check, "_cache_path", lambda: str(cache))
        cache.write_text(json.dumps({"latest": "99.0.0", "checked_at": time.time()}))
        assert _read_cache(ttl=3600) is None


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


class TestFetchLatestVersion:
    def test_targets_fork(self):
        assert version_check.GITHUB_REPO == "josephcrowell/token-saver"
        assert "josephcrowell/token-saver" in version_check._GITHUB_API_URL
        assert "josephcrowell/token-saver" in version_check._MAIN_VERSION_URL
        assert "ppgranger" not in version_check._GITHUB_API_URL

    def test_uses_latest_release_tag(self, monkeypatch):
        urls = []

        def fake_urlopen(req, timeout):
            urls.append(req.full_url)
            return _FakeResponse(json.dumps({"tag_name": "v3.1.0"}).encode())

        monkeypatch.setattr(version_check.urllib.request, "urlopen", fake_urlopen)
        assert version_check._fetch_latest_version(timeout=1) == "3.1.0"
        assert urls == [version_check._GITHUB_API_URL]

    def test_falls_back_to_main_version_without_releases(self, monkeypatch):
        urls = []

        def fake_urlopen(req, timeout):
            urls.append(req.full_url)
            if req.full_url == version_check._GITHUB_API_URL:
                raise urllib.error.HTTPError(req.full_url, 404, "Not Found", None, None)
            return _FakeResponse(b'"""pkg"""\n\n__version__ = "2.7.0"\n')

        monkeypatch.setattr(version_check.urllib.request, "urlopen", fake_urlopen)
        assert version_check._fetch_latest_version(timeout=1) == "2.7.0"
        assert urls == [version_check._GITHUB_API_URL, version_check._MAIN_VERSION_URL]

    def test_other_http_errors_propagate(self, monkeypatch):
        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 403, "rate limited", None, None)

        monkeypatch.setattr(version_check.urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(urllib.error.HTTPError):
            version_check._fetch_latest_version(timeout=1)
