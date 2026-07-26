import asyncio

from . import db
from .slides import REGISTRY

EMPTY_HTML = '<div class="slide slide-empty"><h2>No slides configured</h2><p>Visit /admin to add one.</p></div>'
UNAVAILABLE_SKIP_DELAY = 2


class RotationState:
    def __init__(self) -> None:
        self.current_id: int | None = None
        self.current_html: str = EMPTY_HTML
        self._lock = asyncio.Lock()

    async def set_current(self, slide_id: int | None, html: str) -> None:
        async with self._lock:
            self.current_id = slide_id
            self.current_html = html

    async def snapshot(self) -> dict:
        async with self._lock:
            return {"id": self.current_id, "html": self.current_html}


STATE = RotationState()


async def rotation_loop() -> None:
    while True:
        slides = await db.list_slides(enabled_only=True)
        if not slides:
            await STATE.set_current(None, EMPTY_HTML)
            await asyncio.sleep(5)
            continue

        interval = int(await db.get_setting("rotation_interval_seconds", "60"))
        shown_any = False

        for slide in slides:
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
                html = await slide_type.render(slide["config"])
            except Exception:
                continue

            shown_any = True
            await STATE.set_current(slide["id"], html)
            await asyncio.sleep(interval)

        if not shown_any:
            await STATE.set_current(None, EMPTY_HTML)
            await asyncio.sleep(UNAVAILABLE_SKIP_DELAY)
