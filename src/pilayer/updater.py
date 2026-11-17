"""Update check: GitHub releases comparison. Network only when opt-in/manual."""

import json
import urllib.request

from . import __version__

API = "https://api.github.com/repos/FanKang2021/privacy-input-layer/releases/latest"


def _parts(v: str):
    return tuple(int(x) for x in v.lstrip("v").split(".") if x.isdigit())


def newer(latest: str, current: str = __version__) -> bool:
    return _parts(latest) > _parts(current)


def check_update() -> tuple[str, dict | None]:
    """Return ("newer", {"latest","url"}) / ("current", None) / ("error", None)."""
    try:
        req = urllib.request.Request(API, headers={"User-Agent": "privacy-input-layer"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.load(r)
        tag = data.get("tag_name", "")
        if tag and newer(tag):
            return "newer", {"latest": tag.lstrip("v"), "url": data.get("html_url", "")}
        return "current", None
    except Exception:
        return "error", None