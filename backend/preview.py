import asyncio
import os
import time
from pathlib import Path

MIN_CAPTURE_INTERVAL = 3
CAPTURE_PATH = Path("/tmp/signage-preview.png")
XAUTH_PATH = Path.home() / ".signage-xauth"

_lock = asyncio.Lock()
_cache: dict = {"ts": 0.0, "bytes": b""}


async def get_preview_png() -> bytes | None:
    async with _lock:
        now = time.monotonic()
        if now - _cache["ts"] < MIN_CAPTURE_INTERVAL and _cache["bytes"]:
            return _cache["bytes"]

        env = {**os.environ, "DISPLAY": ":0", "XAUTHORITY": str(XAUTH_PATH)}
        proc = await asyncio.create_subprocess_exec(
            "scrot", "--overwrite", str(CAPTURE_PATH),
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            return _cache["bytes"] or None

        if proc.returncode == 0 and CAPTURE_PATH.exists():
            _cache["bytes"] = CAPTURE_PATH.read_bytes()
            _cache["ts"] = now

        return _cache["bytes"] or None
