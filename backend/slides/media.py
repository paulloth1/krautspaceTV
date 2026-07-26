from markupsafe import escape

from .registry import ConfigField, SlideType, register


async def is_available(config: dict) -> bool:
    return bool(config.get("src"))


async def render(config: dict) -> str:
    kind = config.get("kind", "image")
    src = config.get("src", "")
    if kind == "video":
        body = f'<video src="{escape(src)}" autoplay muted loop playsinline></video>'
    elif kind == "url":
        body = f'<iframe src="{escape(src)}"></iframe>'
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
        ],
        is_available=is_available,
        render=render,
    )
)
