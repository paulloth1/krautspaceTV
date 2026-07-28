import asyncio
import time

from . import db
from .slides import REGISTRY

EMPTY_HTML = '<div class="slide slide-empty"><h2>No slides configured</h2><p>Visit /admin to add one.</p></div>'
ERROR_HTML = '<div class="slide slide-empty"><h2>Error rendering slide</h2></div>'
UNAVAILABLE_SKIP_DELAY = 2


class RotationState:
    def __init__(self) -> None:
        self.current_id: int | None = None
        self.current_html: str = EMPTY_HTML
        self.current_forced: bool = False
        self.current_started_at: float = 0.0
        self.current_interval: float = 0.0
        self.forced_id: int | None = None
        self._lock = asyncio.Lock()
        self._forced_event = asyncio.Event()

    async def set_current(
        self, slide_id: int | None, html: str, forced: bool = False, interval: float = 0.0
    ) -> None:
        async with self._lock:
            self.current_id = slide_id
            self.current_html = html
            self.current_forced = forced
            self.current_started_at = time.monotonic()
            self.current_interval = interval

    async def snapshot(self) -> dict:
        async with self._lock:
            remaining = None
            if self.current_interval:
                elapsed = time.monotonic() - self.current_started_at
                remaining = max(0, round(self.current_interval - elapsed))
            return {
                "id": self.current_id,
                "html": self.current_html,
                "forced": self.current_forced,
                "seconds_remaining": remaining,
            }

    async def request_forced(self, slide_id: int) -> None:
        async with self._lock:
            self.forced_id = slide_id
        self._forced_event.set()

    async def take_forced(self) -> int | None:
        async with self._lock:
            slide_id = self.forced_id
            self.forced_id = None
        self._forced_event.clear()
        return slide_id

    async def is_forced_pending(self) -> bool:
        async with self._lock:
            return self.forced_id is not None

    async def interruptible_sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._forced_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass


STATE = RotationState()


async def _render_forced(slide_id: int) -> bool:
    slide = await db.get_slide(slide_id)
    if slide is None:
        return False
    slide_type = REGISTRY.get(slide["type"])
    if slide_type is None:
        return False
    try:
        html = await slide_type.render(slide["config"], slide["id"])
    except Exception:
        html = ERROR_HTML
    interval = int(await db.get_setting("rotation_interval_seconds", "60"))
    await STATE.set_current(slide["id"], html, forced=True, interval=interval)
    await STATE.interruptible_sleep(interval)
    return True


async def rotation_loop() -> None:
    while True:
        forced_id = await STATE.take_forced()
        if forced_id is not None and await _render_forced(forced_id):
            continue

        slides = await db.list_slides(enabled_only=True)
        if not slides:
            await STATE.set_current(None, EMPTY_HTML)
            await STATE.interruptible_sleep(5)
            continue

        interval = int(await db.get_setting("rotation_interval_seconds", "60"))
        shown_any = False

        for slide in slides:
            if await STATE.is_forced_pending():
                break

            slide_type = REGISTRY.get(slide["type"])
            if slide_type is None:
                continue
            try:
                available = await slide_type.is_available(slide["config"])
            except Exception:
                available = False
            if not available:
                continue
            try:
                html = await slide_type.render(slide["config"], slide["id"])
            except Exception:
                continue

            shown_any = True
            await STATE.set_current(slide["id"], html, interval=interval)
            await STATE.interruptible_sleep(interval)

            if await STATE.is_forced_pending():
                break

        if not shown_any:
            await STATE.set_current(None, EMPTY_HTML)
            await STATE.interruptible_sleep(UNAVAILABLE_SKIP_DELAY)
