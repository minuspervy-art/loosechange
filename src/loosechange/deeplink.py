"""`loosechange://add?model=…&to=…&profile=…` — the one-click install link (docs/DIALOG.md).

Telegram buttons may only open http(s)/tg:// URLs, so the bot links to a static page
(site/add.html on GitHub Pages) that hands over to this scheme; the local handler app
asks the user to confirm and then runs the same adapters as `loosechange add`.

The link is untrusted input (any web page can contain one): parsing is strict, only
these three fields exist, and nothing in it is ever passed to a shell.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlsplit

from .core.profiles import PROFILES

SCHEME = "loosechange"
ACTION = "add"
TARGETS = ("hermes", "vibeforge", "deepseek")  # "other" has nothing to install
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}/[A-Za-z0-9][A-Za-z0-9._:~-]{0,127}")
FIELDS = {"model", "to", "profile"}


@dataclass(frozen=True)
class Request:
    model: str
    target: str
    profile: str


def query(model_id: str, target: str, profile: str) -> str:
    return urlencode({"model": model_id, "to": target, "profile": profile})


def build(model_id: str, target: str, profile: str) -> str:
    return f"{SCHEME}://{ACTION}?{query(model_id, target, profile)}"


def page_url(base: str, model_id: str, target: str, profile: str) -> str:
    """The https page the Telegram button opens (base = where site/ is published)."""
    return f"{base.rstrip('/')}/add.html?{query(model_id, target, profile)}"


def parse(url: str) -> Request:
    parts = urlsplit(url.strip())
    if parts.scheme != SCHEME:
        raise ValueError(f"not a {SCHEME}:// link")
    action = parts.netloc or parts.path.strip("/")
    if action != ACTION:
        raise ValueError(f"unknown action {action!r}")
    raw = parse_qs(parts.query, keep_blank_values=True, strict_parsing=False)
    unknown = set(raw) - FIELDS
    if unknown:
        raise ValueError(f"unexpected fields: {', '.join(sorted(unknown))}")
    if any(len(v) != 1 for v in raw.values()) or set(raw) != FIELDS:
        raise ValueError("model, to and profile must each be given exactly once")
    model, target, profile = raw["model"][0], raw["to"][0], raw["profile"][0]
    if not MODEL_RE.fullmatch(model):
        raise ValueError("malformed model id")
    if target not in TARGETS:
        raise ValueError(f"unknown target {target!r}")
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}")
    return Request(model=model, target=target, profile=profile)
