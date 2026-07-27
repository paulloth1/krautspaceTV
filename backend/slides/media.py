from markupsafe import escape

from .registry import ConfigField, SlideType, register


async def is_available(config: dict) -> bool:
    return bool(config.get("src"))


def _parse_scale(config: dict) -> float:
    try:
        scale = float(config.get("scale") or 1)
    except ValueError:
        scale = 1
    return scale if scale > 0 else 1


async def render(config: dict) -> str:
    kind = config.get("kind", "image")
    src = config.get("src", "")
    scale = _parse_scale(config)

    if kind == "video":
        body = f'<video src="{escape(src)}" autoplay muted loop playsinline></video>'
    elif kind == "url":
        if scale != 1:
            inv = 100 / scale
            style = (
                f"width:{inv}%;height:{inv}%;border:none;"
                f"transform:scale({scale});transform-origin:top left;"
            )
            body = f'<iframe src="{escape(src)}" scrolling="no" style="{style}"></iframe>'
        else:
            body = f'<iframe src="{escape(src)}" scrolling="no"></iframe>'
    else:
        body = f'<img src="{escape(src)}" alt="media">'
    return f'<div class="slide slide-media slide-media-{escape(kind)}">{body}</div>'


register(
    SlideType(
        key="media",
        label="Other media (image / video / URL)",
        config_fields=[
            ConfigField(
                name="kind", label="Kind", type="select", options=["image", "video", "url"], default="image"
            ),
            ConfigField(name="src", label="Source (file path or URL)"),
            ConfigField(
                name="scale",
                label="Zoom scale for URL embeds (e.g. 3 for a small widget that won't fill the screen)",
                type="number",
                required=False,
                default="1",
            ),
        ],
        is_available=is_available,
        render=render,
    )
)
