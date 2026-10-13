"""Task profiles: weights and hard requirements (docs/RANKING.md).

Changing a weight changes every user's recommendations — a PR doing that must
explain why (see docs/RANKING.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Priority(StrEnum):
    QUALITY = "quality"
    STABILITY = "stability"
    CONTEXT = "context"


@dataclass(frozen=True)
class Profile:
    key: str
    weights: dict[str, float]  # component -> weight, components see rank.COMPONENTS
    primary: str  # without this component the model is unrated for the profile
    min_ctx: int = 0
    needs_tools: bool = False
    needs_reasoning: bool = False
    prefers_tools: bool = False  # soft: -NO_TOOLS_PENALTY when missing
    fallback: str | None = None  # component used when `primary` is missing (design)
    title: dict[str, str] = field(default_factory=dict)


PROFILES: dict[str, Profile] = {
    p.key: p
    for p in (
        Profile(
            "agent",
            {"agentic": 0.5, "coding": 0.3, "intelligence": 0.2},
            primary="agentic",
            min_ctx=128_000,
            needs_tools=True,
            title={"ru": "Агент с инструментами", "en": "Agent with tools"},
        ),
        Profile(
            "coding",
            {"coding": 0.7, "intelligence": 0.3},
            primary="coding",
            prefers_tools=True,
            title={"ru": "Код", "en": "Coding"},
        ),
        Profile(
            "chat",
            {"intelligence": 1.0},
            primary="intelligence",
            title={"ru": "Чат / общие вопросы", "en": "Chat / general"},
        ),
        Profile(
            "reasoning",
            {"intelligence": 0.7, "coding": 0.3},
            primary="intelligence",
            needs_reasoning=True,
            title={"ru": "Рассуждения / математика", "en": "Reasoning / math"},
        ),
        Profile(
            "longctx",
            {"intelligence": 0.5, "ctx": 0.5},
            primary="intelligence",
            min_ctx=256_000,
            title={"ru": "Длинные документы", "en": "Long documents"},
        ),
        Profile(
            "fast_cheap",
            {"intelligence": 0.4, "speed": 0.6},
            primary="intelligence",
            title={"ru": "Быстро и дёшево", "en": "Fast & cheap"},
        ),
        Profile(
            "design",
            {"design": 1.0},
            primary="design",
            fallback="coding",
            title={"ru": "Дизайн / вёрстка", "en": "Design / web UI"},
        ),
    )
}

DEFAULT_PROFILE = "agent"

# Reliability / priority knobs
LOW_UPTIME = 90.0  # % over the last 30 min
LOW_UPTIME_PENALTY = 10.0
NO_TOOLS_PENALTY = 5.0
EXPIRY_WARN_DAYS = 7
PRIORITY_BLEND = 0.2  # share of the final score given to uptime / context for those priorities


def get_profile(key: str) -> Profile:
    try:
        return PROFILES[key]
    except KeyError:
        raise ValueError(f"unknown profile {key!r}; choose from {', '.join(PROFILES)}") from None
