from dataclasses import dataclass, field
from typing import Awaitable, Callable


@dataclass
class ConfigField:
    name: str
    label: str
    type: str = "text"  # text, password, number, textarea, select
    required: bool = True
    options: list[str] = field(default_factory=list)  # for type == "select"
    default: str = ""


@dataclass
class SlideType:
    key: str
    label: str
    config_fields: list[ConfigField]
    is_available: Callable[[dict], Awaitable[bool]]
    render: Callable[[dict, int | None], Awaitable[str]]


REGISTRY: dict[str, SlideType] = {}


def register(slide_type: SlideType) -> None:
    REGISTRY[slide_type.key] = slide_type
