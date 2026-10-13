"""/pick dialog: callback data, keyboards, free-text -> profile rules (docs/DIALOG.md)."""

from __future__ import annotations

import hashlib
import re

from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup

from ..core.profiles import PROFILES, Priority
from ..core.rank import RankResult
from ..integrations import TARGETS, Snippet
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


def model_key(model_id: str) -> str:
    """Short stable reference to a model for callback data (64-byte limit). Buttons
    point at the model itself, so the timed data refresh never makes them stale."""
    return hashlib.sha1(model_id.encode()).hexdigest()[:10]


class AddCb(CallbackData, prefix="a"):
    """Snippet for model `key` (see model_key) to `target`; profile names the alias."""

    profile: str
    target: str
    key: str


class CardCb(CallbackData, prefix="c"):
    """Snippet for a model shown by /model or /add."""

    key: str
    target: str


class RefreshCb(CallbackData, prefix="r"):
    """Re-rank with the current data (the «🔄 Обновить» button)."""

    profile: str
    priority: str
    target: str  # "-" when unknown


class MenuCb(CallbackData, prefix="m"):
    action: str  # home | pick | top | new


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
    return InlineKeyboardMarkup(inline_keyboard=_rows(btns, 2))


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


def nav_row(
    lang: str, profile: str, priority: str, target: str | None
) -> list[InlineKeyboardButton]:
    """Bottom row: back to the main menu | re-run the same pick with fresh data."""
    return [
        InlineKeyboardButton(text=t(lang, "btn_menu"), callback_data=MenuCb(action="home").pack()),
        InlineKeyboardButton(
            text=t(lang, "btn_refresh"),
            callback_data=RefreshCb(
                profile=profile, priority=priority, target=target or "-"
            ).pack(),
        ),
    ]


def menu_kb(lang: str) -> InlineKeyboardMarkup:
    btns = [
        InlineKeyboardButton(text=t(lang, f"menu_{a}"), callback_data=MenuCb(action=a).pack())
        for a in ("pick", "top", "new")
    ]
    return InlineKeyboardMarkup(inline_keyboard=[btns])


def result_kb(
    result: RankResult,
    lang: str,
    target: str | None,
    page: int,
    pages: int,
    page_size: int,
) -> InlineKeyboardMarkup:
    """Add-buttons for the models on this page + pagination + menu/refresh row."""
    rows: list[list[InlineKeyboardButton]] = []
    prof, prio = result.profile.key, result.priority.value
    chunk = result.all[page * page_size : (page + 1) * page_size]
    targets = [target] if target else ["hermes", "vibeforge", "deepseek"]
    for s in chunk:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(lang, "add_btn", rank=s.rank, target=t(lang, f"ts_{tg}")),
                    callback_data=AddCb(profile=prof, target=tg, key=model_key(s.model.id)).pack(),
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
    rows.append(nav_row(lang, prof, prio, target))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def card_kb(model_id: str, lang: str) -> InlineKeyboardMarkup:
    btns = [
        InlineKeyboardButton(
            text=t(lang, "card_add", target=t(lang, f"t_{tg}")),
            callback_data=CardCb(key=model_key(model_id), target=tg).pack(),
        )
        for tg in TARGETS
    ]
    menu = InlineKeyboardButton(
        text=t(lang, "btn_menu"), callback_data=MenuCb(action="home").pack()
    )
    return InlineKeyboardMarkup(inline_keyboard=[*_rows(btns, 2), [menu]])


COPY_TEXT_LIMIT = 256  # Telegram limit for CopyTextButton.text


def copy_kb(snippet: Snippet, lang: str) -> InlineKeyboardMarkup:
    """One tap puts the ready command (or the model id) on the clipboard; + menu."""
    rows = []
    text = snippet.copy_text
    if text and len(text) <= COPY_TEXT_LIMIT:
        label = t(lang, "copy_cmd" if text == snippet.command else "copy_id")
        rows.append([InlineKeyboardButton(text=label, copy_text=CopyTextButton(text=text))])
    rows.append(
        [InlineKeyboardButton(text=t(lang, "btn_menu"), callback_data=MenuCb(action="home").pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
