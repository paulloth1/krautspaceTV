import asyncio

from backend import preview


class _FakeProc:
    def __init__(self, returncode=0):
        self.returncode = returncode
        self.killed = False

    async def wait(self):
        return self.returncode

    def kill(self):
        self.killed = True


def _fresh_cache(ts=0.0, data=b""):
    return {"ts": ts, "bytes": data}


# ---------------------------------------------------------------------------
# successful capture + caching
# ---------------------------------------------------------------------------


async def test_get_preview_png_captures_via_scrot_and_returns_bytes(monkeypatch, tmp_path):
    capture_path = tmp_path / "preview.png"
    capture_path.write_bytes(b"screenshot-bytes")
    monkeypatch.setattr(preview, "CAPTURE_PATH", capture_path)
    monkeypatch.setattr(preview, "_cache", _fresh_cache())

    seen = {"count": 0, "args": None, "env": None}

    async def _fake_exec(*args, **kwargs):
        seen["count"] += 1
        seen["args"] = args
        seen["env"] = kwargs.get("env")
        return _FakeProc(returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    result = await preview.get_preview_png()

    assert result == b"screenshot-bytes"
    assert seen["count"] == 1
    assert seen["args"][0] == "scrot"
    assert str(capture_path) in seen["args"]
    assert seen["env"]["DISPLAY"] == ":0"


async def test_get_preview_png_second_call_within_interval_uses_cache(monkeypatch, tmp_path):
    capture_path = tmp_path / "preview.png"
    capture_path.write_bytes(b"screenshot-bytes")
    monkeypatch.setattr(preview, "CAPTURE_PATH", capture_path)
    monkeypatch.setattr(preview, "_cache", _fresh_cache())

    calls = {"count": 0}

    async def _fake_exec(*args, **kwargs):
        calls["count"] += 1
        return _FakeProc(returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    first = await preview.get_preview_png()
    second = await preview.get_preview_png()

    assert first == second == b"screenshot-bytes"
    # The second call landed well inside MIN_CAPTURE_INTERVAL, so scrot must
    # not have been invoked a second time.
    assert calls["count"] == 1


async def test_get_preview_png_recaptures_after_interval_elapses(monkeypatch, tmp_path):
    capture_path = tmp_path / "preview.png"
    capture_path.write_bytes(b"first-bytes")
    monkeypatch.setattr(preview, "CAPTURE_PATH", capture_path)
    # Backdate the cache far enough that MIN_CAPTURE_INTERVAL has "elapsed".
    monkeypatch.setattr(preview, "_cache", _fresh_cache(ts=-1000.0, data=b"stale-bytes"))

    calls = {"count": 0}

    async def _fake_exec(*args, **kwargs):
        calls["count"] += 1
        return _FakeProc(returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    result = await preview.get_preview_png()

    assert result == b"first-bytes"
    assert calls["count"] == 1


# ---------------------------------------------------------------------------
# capture failure paths
# ---------------------------------------------------------------------------


async def test_get_preview_png_returns_none_when_scrot_fails_and_no_prior_cache(
    monkeypatch, tmp_path
):
    capture_path = tmp_path / "preview.png"  # never written, scrot "failed"
    monkeypatch.setattr(preview, "CAPTURE_PATH", capture_path)
    monkeypatch.setattr(preview, "_cache", _fresh_cache())

    async def _fake_exec(*args, **kwargs):
        return _FakeProc(returncode=1)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    assert await preview.get_preview_png() is None


async def test_get_preview_png_returns_stale_cache_when_scrot_fails(monkeypatch, tmp_path):
    capture_path = tmp_path / "preview.png"
    monkeypatch.setattr(preview, "CAPTURE_PATH", capture_path)
    monkeypatch.setattr(preview, "_cache", _fresh_cache(ts=-1000.0, data=b"old-bytes"))

    async def _fake_exec(*args, **kwargs):
        return _FakeProc(returncode=1)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    assert await preview.get_preview_png() == b"old-bytes"


async def test_get_preview_png_returns_none_when_returncode_ok_but_file_missing(
    monkeypatch, tmp_path
):
    capture_path = tmp_path / "preview.png"  # scrot "succeeded" but wrote nothing
    monkeypatch.setattr(preview, "CAPTURE_PATH", capture_path)
    monkeypatch.setattr(preview, "_cache", _fresh_cache())

    async def _fake_exec(*args, **kwargs):
        return _FakeProc(returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    assert await preview.get_preview_png() is None


# ---------------------------------------------------------------------------
# timeout path
# ---------------------------------------------------------------------------


async def test_get_preview_png_kills_process_and_returns_none_on_timeout(monkeypatch, tmp_path):
    capture_path = tmp_path / "preview.png"
    monkeypatch.setattr(preview, "CAPTURE_PATH", capture_path)
    monkeypatch.setattr(preview, "_cache", _fresh_cache())

    proc = _FakeProc(returncode=0)

    async def _fake_exec(*args, **kwargs):
        return proc

    async def _fake_wait_for(coro, timeout):
        coro.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    monkeypatch.setattr(asyncio, "wait_for", _fake_wait_for)

    result = await preview.get_preview_png()

    assert result is None
    assert proc.killed is True


async def test_get_preview_png_returns_stale_cache_on_timeout(monkeypatch, tmp_path):
    capture_path = tmp_path / "preview.png"
    monkeypatch.setattr(preview, "CAPTURE_PATH", capture_path)
    monkeypatch.setattr(preview, "_cache", _fresh_cache(ts=-1000.0, data=b"cached-bytes"))

    proc = _FakeProc(returncode=0)

    async def _fake_exec(*args, **kwargs):
        return proc

    async def _fake_wait_for(coro, timeout):
        coro.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    monkeypatch.setattr(asyncio, "wait_for", _fake_wait_for)

    result = await preview.get_preview_png()

    assert result == b"cached-bytes"
    assert proc.killed is True
