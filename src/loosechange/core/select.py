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


def broken_for(m: Model | None, harness: bool) -> str | None:
    """Why this model should not be used now (None = fine)."""
    if m is None:
        return "no longer a free model"
    if m.harness_only and not harness:
        return "harness-only (403 in a plain client)"
    if m.congested:
        return f"rate-limited upstream (429 at {m.congested_at:%H:%M} UTC)"
    return None


def choose(
    snapshot: Snapshot,
    current_default: str | None,
    top: int = 3,
    profile: str = "agent",
    today: date | None = None,
    harness: bool = False,
) -> Selection:
    """Top-`top` rated models, verified-open first; flaky (low uptime) and congested
    (recent 429) ones skipped; harness-only ones only when `harness` (Hermes, DSH).
    The default is replaced only when it is empty, gone, unusable here, or congested —
    a working choice of the user stays."""
    usable = [
        m
        for m in snapshot.models
        if not m.is_router and not m.congested and (harness or not m.harness_only)
    ]
    result = rank(usable, get_profile(profile), Priority.QUALITY, today=today or date.today())
    ranked = [s for s in result.rated if LOW_UPTIME_FLAG not in s.flags]
    verified = {"open", "harness_only"} if harness else {"open"}
    ranked.sort(key=lambda s: (s.model.access not in verified, s.rank))
    sel = Selection(picks=[s.model for s in ranked[:top]])

    default = (current_default or "").strip()
    if not default:
        reason = "no default model"
    else:
        why = broken_for(snapshot.get(default), harness)
        reason = f"default {default} is {why}" if why else None
    if reason and sel.picks:
        sel.new_default = sel.picks[0].id
        sel.reasons.append(f"{reason} -> {sel.new_default}")
    return sel
