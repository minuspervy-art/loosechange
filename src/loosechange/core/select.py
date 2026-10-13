"""Pick models for a client that calls OpenRouter directly (VibeForge's API engine).

Pure: works on a snapshot, no network. Used by `loosechange sync`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .profiles import Priority, get_profile
from .rank import LOW_UPTIME_FLAG, rank
from .schema import Model, Snapshot


@dataclass
class Selection:
    picks: list[Model] = field(default_factory=list)
    new_default: str | None = None  # None = keep the current default
    reasons: list[str] = field(default_factory=list)


def usable_for_plain_client(m: Model) -> bool:
    return not m.harness_only and not m.is_router


def choose(
    snapshot: Snapshot,
    current_default: str | None,
    top: int = 3,
    profile: str = "agent",
    today: date | None = None,
) -> Selection:
    """Top-`top` rated models that a plain client can call, verified-open first and
    flaky (low uptime) ones skipped. The default is replaced only when it is empty,
    gone from the free list, or harness-only — a working choice of the user stays."""
    usable = [m for m in snapshot.models if usable_for_plain_client(m)]
    result = rank(usable, get_profile(profile), Priority.QUALITY, today=today or date.today())
    ranked = [s for s in result.rated if LOW_UPTIME_FLAG not in s.flags]
    ranked.sort(key=lambda s: (s.model.access != "open", s.rank))
    sel = Selection(picks=[s.model for s in ranked[:top]])

    default = (current_default or "").strip()
    current = snapshot.get(default) if default else None
    if not default:
        reason = "no default model"
    elif current is None:
        reason = f"default {default} is no longer a free model"
    elif current.harness_only:
        reason = f"default {default} is harness-only (403 in a plain client)"
    else:
        reason = None
    if reason and sel.picks:
        sel.new_default = sel.picks[0].id
        sel.reasons.append(f"{reason} -> {sel.new_default}")
    return sel
