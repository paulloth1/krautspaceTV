from markupsafe import escape

import httpx

from .registry import ConfigField, SlideType, register


async def is_available(config: dict) -> bool:
    url = config.get("url", "")
    if not url:
        return False
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            async with client.stream("GET", url) as resp:
                return resp.status_code < 400
    except httpx.HTTPError:
        return False


async def render(config: dict) -> str:
    url = config.get("url", "")
    label = config.get("label") or "Webcam"
    return (
        f'<div class="slide slide-webcam">'
        f'<h2>{escape(label)}</h2>'
        f'<img class="webcam-feed" src="{escape(url)}" alt="{escape(label)}">'
        f'</div>'
    )


register(
    SlideType(
        key="webcam",
        label="Webcam (MJPEG stream)",
        config_fields=[
            ConfigField(name="url", label="Stream URL"),
            ConfigField(name="label", label="Display label", required=False),
        ],
        is_available=is_available,
        render=render,
    )
)
