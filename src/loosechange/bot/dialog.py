"""/pick dialog: callback data, keyboards, free-text -> profile rules (docs/DIALOG.md)."""

from __future__ import annotations

import re

from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..integrations import TARGETS
from ..profiles import PROFILES, Priority
from ..rank import RankResult
from .i18n import LANGS, t

PURPOSES = ("agent", "coding", "chat", "reasoning", "longctx", "fast_cheap", "design")


class Pick(StatesGroup):
    freeform = State()


class PickCb(CallbackData, prefix="p"):
    step: str  # purpose | target | priority
    value: str


class PageCb(CallbackData, prefix="g"):
    profile: str
    priority: str
    target: str  # "-" when unknown
    page: int


class AddCb(CallbackData, prefix="a"):
    """Snippet for the model at `rank` of ranking(profile, priority) — stateless."""

    profile: str
    priority: str
    rank: int
    target: str
    ver: int  # DataStore.version; a newer snapshot may reorder ranks


class CardCb(CallbackData, prefix="c"):
    """Snippet for a model shown by /model; idx points into the snapshot list."""

    idx: int
    target: str
    ver: int


class LangCb(CallbackData, prefix="l"):
    lang: str


def _rows(buttons: list[InlineKeyboardButton], per_row: int) -> list[list[InlineKeyboardButton]]:
    return [buttons[i : i + per_row] for i in range(0, len(buttons), per_row)]


def purpose_kb(lang: str) -> InlineKeyboardMarkup:
    keys = [*PURPOSES, "unknown"]
    btns = [
        InlineKeyboardButton(
            text=t(lang, f"p_{k}"), callback_data=PickCb(step="purpose", value=k).pack()
        )
        for k in keys
    ]
    return InlineKeyboardMarkup(inline_keyboard=_rows(btns, 2))


def target_kb(lang: str) -> InlineKeyboardMarkup:
    btns = [
        InlineKeyboardButton(
            text=t(lang, f"t_{k}"), callback_data=PickCb(step="target", value=k).pack()
        )
        for k in TARGETS
    ]
    return InlineKeyboardMarkup(inline_keyboard=[btns])


def priority_kb(lang: str) -> InlineKeyboardMarkup:
    btns = [
        InlineKeyboardButton(
            text=t(lang, f"pr_{p.value}"),
            callback_data=PickCb(step="priority", value=p.value).pack(),
        )
        for p in Priority
    ]
    return InlineKeyboardMarkup(inline_keyboard=_rows(btns, 1))


def lang_kb() -> InlineKeyboardMarkup:
    names = {"ru": "🇷🇺 Русский", "en": "🇬🇧 English"}
    btns = [InlineKeyboardButton(text=names[k], callback_data=LangCb(lang=k).pack()) for k in LANGS]
    return InlineKeyboardMarkup(inline_keyboard=[btns])


def result_kb(
    result: RankResult,
    lang: str,
    target: str | None,
    page: int,
    pages: int,
    page_size: int,
    ver: int,
) -> InlineKeyboardMarkup:
    """Add-buttons for the models on this page + pagination."""
    rows: list[list[InlineKeyboardButton]] = []
    prof, prio = result.profile.key, result.priority.value
    chunk = result.all[page * page_size : (page + 1) * page_size]
    targets = [target] if target else ["hermes", "vibeforge"]
    for s in chunk:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(lang, "add_btn", rank=s.rank, target=t(lang, f"t_{tg}")),
                    callback_data=AddCb(
                        profile=prof, priority=prio, rank=s.rank, target=tg, ver=ver
                    ).pack(),
                )
                for tg in targets
            ]
        )
    nav = []
    tg = target or "-"
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="◀",
                callback_data=PageCb(profile=prof, priority=prio, target=tg, page=page - 1).pack(),
            )
        )
    if page == 0 and pages > 1:
        nav.append(
            InlineKeyboardButton(
                text=t(lang, "show_all", n=len(result.all)),
                callback_data=PageCb(profile=prof, priority=prio, target=tg, page=1).pack(),
            )
        )
    elif page < pages - 1:
        nav.append(
            InlineKeyboardButton(
                text="▶",
                callback_data=PageCb(profile=prof, priority=prio, target=tg, page=page + 1).pack(),
            )
        )
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def card_kb(idx: int, lang: str, ver: int) -> InlineKeyboardMarkup:
    btns = [
        InlineKeyboardButton(
            text=t(lang, "card_add", target=t(lang, f"t_{tg}")),
            callback_data=CardCb(idx=idx, target=tg, ver=ver).pack(),
        )
        for tg in TARGETS
    ]
    return InlineKeyboardMarkup(inline_keyboard=[btns])


# ---------------------------------------------------------------- free text -> profile
# Simple keyword rules (an LLM classifier is v2, see docs/ROADMAP.md). Order matters:
# the first matching rule wins.
RULES: list[tuple[str, str]] = [
    (
        "design",
        r"дизайн|вёрст|верст|лендинг|ui\b|ux\b|css|html|figma|svg|design|landing|frontend|фронтенд",
    ),
    ("agent", r"агент|hermes|vibeforge|инструмент|tool|agent|автоматиз|mcp|function.?call"),
    ("longctx", r"документ|pdf|книг|длинн|контекст|договор|статей|document|long|book|context"),
    ("reasoning", r"матем|логик|рассужд|задач[аи] по|олимпиад|доказ|math|reason|logic|proof"),
    ("fast_cheap", r"класси|саммари|резюм|быстр|дешев|дёшев|summar|classif|fast|cheap|tag"),
    (
        "coding",
        r"код|програм|python|питон|javascript|js\b|rust|go\b|баг|рефактор|скрипт|бот|sql|code|coding|bug|script",
    ),
    ("chat", r".*"),
]


def guess_profile(text: str) -> str:
    low = text.lower()
    for profile, pattern in RULES:
        if re.search(pattern, low):
            return profile
    return "chat"


def preselected_profile(arg: str | None) -> str | None:
    """`/pick agent` skips question 1."""
    if not arg:
        return None
    key = arg.strip().lower().replace("-", "_")
    return key if key in PROFILES else None
