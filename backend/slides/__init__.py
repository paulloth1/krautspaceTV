# ruff: noqa: I001 — import order here is deliberate, not alphabetical: each slide
# module registers itself into REGISTRY on import, and REGISTRY's insertion order
# is what the admin UI's slide-type picker lists. Re-sorting reorders that menu.
from .registry import REGISTRY  # noqa: F401
from . import webcam, matrix, train, media, mastodon, api_status, rss  # noqa: F401
