"""Pure ranking functions: no network, no IO (docs/RANKING.md)."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from .models import Model
from .profiles import (
    EXPIRY_WARN_DAYS,
    LOW_UPTIME,
    LOW_UPTIME_PENALTY,
    NO_TOOLS_PENALTY,
    PRIORITY_BLEND,
    Priority,
    Profile,
)

COMPONENTS = ("intelligence", "coding", "agentic", "design", "ctx", "speed")

# flags attached to a scored model (rendered as icons/warnings by the bot)
LOW_UPTIME_FLAG = "low_uptime"
EXPIRING_FLAG = "expiring"
NO_TOOLS_FLAG = "no_tools"
FALLBACK_FLAG = "fallback"
NO_UPTIME_FLAG = "no_uptime_data"


def raw_component(m: Model, name: str) -> float | None:
    b = m.benchmarks
    match name:
        case "intelligence":
            return b.intelligence
        case "coding":
            return b.coding
        case "agentic":
            return b.agentic
        case "design":
            return b.design_elo
        case "ctx":
            return math.log(m.context_length) if m.context_length > 0 else None
        case "speed":
            return m.reliability.throughput_30m if m.reliability else None
    raise ValueError(name)


@dataclass
class Scored:
    model: Model
    score: float | None = None
    components: dict[str, float | None] = field(default_factory=dict)  # normalized 0..100
    flags: list[str] = field(default_factory=list)
    rank: int | None = None

    @property
    def rated(self) -> bool:
        return self.score is not None


@dataclass
class RankResult:
    profile: Profile
    priority: Priority
    rated: list[Scored] = field(default_factory=list)
    unrated: list[Scored] = field(default_factory=list)
    available: bool = True
    reason: str | None = None

    @property
    def all(self) -> list[Scored]:
        return self.rated + self.unrated


def meets_requirements(m: Model, p: Profile) -> bool:
    if m.context_length < p.min_ctx:
        return False
    if p.needs_tools and not m.tools:
        return False
    return not (p.needs_reasoning and not m.reasoning)


def normalize_max(values: dict[str, float | None]) -> dict[str, float | None]:
    """Scale to 0..100 by the max among candidates; None stays None."""
    present = [v for v in values.values() if v is not None]
    top = max(present, default=None)
    if not top or top <= 0:
        return {k: (None if v is None else 0.0) for k, v in values.items()}
    return {k: (None if v is None else max(v, 0.0) / top * 100) for k, v in values.items()}


def normalize_log_ctx(values: dict[str, float | None], floor_ctx: int) -> dict[str, float | None]:
    """Min-max on log(ctx), floor = the profile's min context (or the smallest candidate)."""
    present = [v for v in values.values() if v is not None]
    if not present:
        return dict(values)
    lo = math.log(floor_ctx) if floor_ctx > 0 else min(present)
    hi = max(present)
    if hi <= lo:
        return {k: (None if v is None else 100.0) for k, v in values.items()}
    return {
        k: (None if v is None else max(0.0, (v - lo) / (hi - lo) * 100)) for k, v in values.items()
    }


def expires_soon(m: Model, today: date) -> bool:
    return m.expiration_date is not None and (m.expiration_date - today).days <= EXPIRY_WARN_DAYS


def rank(
    models: Iterable[Model],
    profile: Profile,
    priority: Priority | str = Priority.QUALITY,
    today: date | None = None,
) -> RankResult:
    priority = Priority(priority)
    today = today or date.today()
    cands = [m for m in models if meets_requirements(m, profile)]
    result = RankResult(profile=profile, priority=priority)

    if "speed" in profile.weights and all(raw_component(m, "speed") is None for m in cands):
        result.available = False
        result.reason = "no_speed_data"
        return result

    needed = set(profile.weights)
    if profile.fallback:
        needed.add(profile.fallback)
    if priority is Priority.CONTEXT:
        needed.add("ctx")
    norm: dict[str, dict[str, float | None]] = {}
    for comp in needed:
        raw = {m.id: raw_component(m, comp) for m in cands}
        norm[comp] = (
            normalize_log_ctx(raw, profile.min_ctx) if comp == "ctx" else normalize_max(raw)
        )

    for m in cands:
        s = Scored(model=m, components={c: norm[c][m.id] for c in sorted(needed)})
        if expires_soon(m, today):
            s.flags.append(EXPIRING_FLAG)
        score = _base_score(s, profile)
        if score is None:
            result.unrated.append(s)
            continue
        score = _apply_priority(s, score, priority)
        uptime = m.reliability.uptime_30m if m.reliability else None
        if uptime is not None and uptime < LOW_UPTIME:
            score -= LOW_UPTIME_PENALTY
            s.flags.append(LOW_UPTIME_FLAG)
        if profile.prefers_tools and not m.tools:
            score -= NO_TOOLS_PENALTY
            s.flags.append(NO_TOOLS_FLAG)
        s.score = round(max(score, 0.0), 1)
        result.rated.append(s)

    result.rated.sort(key=lambda s: (FALLBACK_FLAG in s.flags, -(s.score or 0), s.model.id))
    result.unrated.sort(key=lambda s: s.model.id)
    for i, s in enumerate(result.all, 1):
        s.rank = i
    return result


def _base_score(s: Scored, p: Profile) -> float | None:
    comps = s.components
    if comps.get(p.primary) is None:
        if p.fallback and comps.get(p.fallback) is not None:
            s.flags.append(FALLBACK_FLAG)
            return comps[p.fallback]
        return None
    present = {c: w for c, w in p.weights.items() if comps.get(c) is not None}
    total = sum(present.values())
    return sum(w * comps[c] for c, w in present.items()) / total


def _apply_priority(s: Scored, score: float, priority: Priority) -> float:
    if priority is Priority.STABILITY:
        uptime = s.model.reliability.uptime_30m if s.model.reliability else None
        if uptime is None:
            s.flags.append(NO_UPTIME_FLAG)
        return (1 - PRIORITY_BLEND) * score + PRIORITY_BLEND * (uptime or 0.0)
    if priority is Priority.CONTEXT:
        return (1 - PRIORITY_BLEND) * score + PRIORITY_BLEND * (s.components.get("ctx") or 0.0)
    return score
