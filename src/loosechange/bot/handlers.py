"""Telegram handlers. Dependencies (`store`, `prefs`) are injected by the dispatcher."""

from __future__ import annotations

import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from html import escape
from typing import Any

from aiogram import BaseMiddleware, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, TelegramObject

from .. import integrations
from ..core.profiles import Priority, get_profile
from ..core.rank import RankResult, rank
from ..core.schema import Model, Snapshot
from . import render
from .dialog import (
    AddCb,
    CardCb,
    LangCb,
    MenuCb,
    PageCb,
    Pick,
    PickCb,
    RefreshCb,
    card_kb,
    copy_kb,
    guess_profile,
    lang_kb,
    menu_kb,
    model_key,
    nav_row,
    preselected_profile,
    priority_kb,
    purpose_kb,
    result_kb,
    target_kb,
)
from .i18n import DEFAULT_LANG, LANGS, t
from .store import DataStore

TOP_PROFILE = "chat"  # /top = general intelligence ranking


@dataclass
class Prefs:
    """In-memory per-user state (lost on restart by design, see docs/ARCHITECTURE.md)."""

    lang: dict[int, str] = field(default_factory=dict)
    last_model: dict[int, str] = field(default_factory=dict)
    last_list: dict[int, tuple[str, str]] = field(default_factory=dict)

    def get_lang(self, user_id: int | None, fallback: str | None = None) -> str:
        if user_id in self.lang:
            return self.lang[user_id]
        code = (fallback or "")[:2]
        return code if code in LANGS else DEFAULT_LANG


class AntiFlood(BaseMiddleware):
    """At most one update per `interval` seconds per user; stores only user_id -> time."""

    def __init__(self, interval: float = 2.0, prefs: Prefs | None = None) -> None:
        self.interval = interval
        self.prefs = prefs
        self.last: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)
        now = time.monotonic()
        if now - self.last.get(user.id, -1e9) < self.interval:
            if isinstance(event, CallbackQuery):
                lang = self.prefs.get_lang(user.id, user.language_code) if self.prefs else "ru"
                await event.answer(t(lang, "flood"))
            return None
        self.last[user.id] = now
        if len(self.last) > 50_000:  # bound memory
            cutoff = now - 60
            self.last = {k: v for k, v in self.last.items() if v > cutoff}
        return await handler(event, data)


_HANDLERS: list[tuple[str, tuple, Callable]] = []


def on(kind: str, *filters: Any) -> Callable:
    """Collect handlers; `build_router()` attaches them to a fresh Router each time."""

    def deco(fn: Callable) -> Callable:
        _HANDLERS.append((kind, filters, fn))
        return fn

    return deco


def build_router() -> Router:
    r = Router(name="loosechange")
    for kind, filters, fn in _HANDLERS:
        getattr(r, kind).register(fn, *filters)
    return r


def _lang(prefs: Prefs, event: Message | CallbackQuery) -> str:
    u = event.from_user
    return prefs.get_lang(u.id if u else None, u.language_code if u else None)


def compute(snapshot: Snapshot, profile: str, priority: str) -> RankResult:
    return rank(snapshot.models, get_profile(profile), Priority(priority), today=date.today())


def find_by_key(snapshot: Snapshot, key: str) -> Model | None:
    return next((m for m in snapshot.models if model_key(m.id) == key), None)


def find_model(snapshot: Snapshot, query: str) -> tuple[int, Model] | None:
    q = query.strip()
    for cand in (q, f"{q}:free"):
        for i, m in enumerate(snapshot.models):
            if m.id == cand:
                return i, m
    return None


async def send_ranking(
    message: Message,
    store: DataStore,
    prefs: Prefs,
    lang: str,
    user_id: int,
    profile: str,
    priority: str,
    target: str | None,
    edit: bool = False,
) -> None:
    """`edit=True` turns the bot's own question message into the result: one Telegram
    call instead of two, which matters on slow networks."""
    snap = await store.get()
    if not snap:
        await message.answer(t(lang, "no_data"))
        return
    result = compute(snap, profile, priority)
    if not result.available:
        await message.answer(t(lang, "fast_unavailable"))
        profile = TOP_PROFILE
        result = compute(snap, profile, priority)
    text, pages = render.ranking_page(result, lang, 0)
    text += render.stale_footer(snap, lang)
    kb = result_kb(result, lang, target, 0, pages, render.PAGE_SIZE)
    prefs.last_list[user_id] = (profile, priority)
    if result.all:
        prefs.last_model[user_id] = result.all[0].model.id
    await _show(message, text, kb, edit)


async def _show(message: Message, text: str, kb: InlineKeyboardMarkup | None, edit: bool) -> None:
    """Edit the bot's message in place (one API call) or send a new one."""
    if edit:
        try:
            await message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
            return
        except TelegramBadRequest as exc:
            if "not modified" in str(exc):  # same content after a refresh: nothing to do
                return
            # message too old / deleted: fall back to a new message
    await message.answer(text, reply_markup=kb, disable_web_page_preview=True)


# ---------------------------------------------------------------- commands


@on("message", CommandStart())
async def cmd_start(message: Message, prefs: Prefs, state: FSMContext) -> None:
    await state.clear()
    lang = _lang(prefs, message)
    await message.answer(t(lang, "start"), reply_markup=menu_kb(lang))


@on("message", Command("about"))
async def cmd_about(message: Message, prefs: Prefs, store: DataStore) -> None:
    lang = _lang(prefs, message)
    snap = await store.get()
    count = len(snap.models) if snap else 0
    ts = snap.generated_at.strftime("%Y-%m-%d %H:%M UTC") if snap else "—"
    text = t(lang, "about", count=count, ts=ts)
    if snap:
        text += "\n" + t(lang, "about_fresh", ago=render.ago(lang, snap.generated_at))
    if store.refresher:
        p = store.refresher.policy
        text += "\n" + t(
            lang,
            "about_timers",
            list=f"{p.list_ttl.total_seconds() / 60:g}",
            full=f"{p.full_ttl.total_seconds() / 60:g}",
        )
    await message.answer(text, disable_web_page_preview=True)


@on("message", Command("lang"))
async def cmd_lang(message: Message) -> None:
    await message.answer("🌐", reply_markup=lang_kb())


@on("callback_query", LangCb.filter())
async def on_lang(cb: CallbackQuery, callback_data: LangCb, prefs: Prefs) -> None:
    prefs.lang[cb.from_user.id] = callback_data.lang
    await cb.answer(t(callback_data.lang, "lang_set"))
    if isinstance(cb.message, Message):
        lang = callback_data.lang
        await cb.message.edit_text(t(lang, "start"), reply_markup=menu_kb(lang))


@on("message", Command("top"))
async def cmd_top(message: Message, command: CommandObject, prefs: Prefs, store: DataStore) -> None:
    lang = _lang(prefs, message)
    profile = preselected_profile(command.args) or TOP_PROFILE
    await send_ranking(
        message, store, prefs, lang, message.from_user.id, profile, Priority.QUALITY.value, None
    )


@on("message", Command("pick"))
async def cmd_pick(
    message: Message, command: CommandObject, prefs: Prefs, state: FSMContext
) -> None:
    lang = _lang(prefs, message)
    await state.clear()
    args = (command.args or "").split()
    profile = preselected_profile(args[0]) if args else None
    target = args[1].lower() if len(args) > 1 and args[1].lower() in integrations.TARGETS else None
    if profile is None:
        await message.answer(t(lang, "q_purpose"), reply_markup=purpose_kb(lang))
        return
    await state.update_data(purpose=profile)
    if target is None:
        await message.answer(t(lang, "q_target"), reply_markup=target_kb(lang))
        return
    await state.update_data(target=target)
    await message.answer(t(lang, "q_priority"), reply_markup=priority_kb(lang))


@on("callback_query", PickCb.filter())
async def on_pick(
    cb: CallbackQuery,
    callback_data: PickCb,
    prefs: Prefs,
    store: DataStore,
    state: FSMContext,
) -> None:
    lang = _lang(prefs, cb)
    msg = cb.message if isinstance(cb.message, Message) else None
    await cb.answer()
    if msg is None:
        return
    step, value = callback_data.step, callback_data.value
    if step == "purpose":
        if value == "unknown":
            await state.set_state(Pick.freeform)
            await msg.edit_text(t(lang, "q_freeform"))
            return
        await state.update_data(purpose=value)
        await msg.edit_text(t(lang, "q_target"), reply_markup=target_kb(lang))
    elif step == "target":
        await state.update_data(target=value)
        await msg.edit_text(t(lang, "q_priority"), reply_markup=priority_kb(lang))
    elif step == "priority":
        data = await state.get_data()
        await state.clear()
        purpose = data.get("purpose")
        if not purpose:  # dialog state lost (e.g. bot restarted): start the pick over
            await msg.edit_text(t(lang, "q_purpose"), reply_markup=purpose_kb(lang))
            return
        await send_ranking(
            msg, store, prefs, lang, cb.from_user.id, purpose, value, data.get("target"), edit=True
        )


@on("message", Pick.freeform, F.text)
async def on_freeform(message: Message, prefs: Prefs, state: FSMContext) -> None:
    lang = _lang(prefs, message)
    profile = guess_profile(message.text or "")
    await state.set_state(None)
    await state.update_data(purpose=profile)
    title = render.profile_title(lang, profile)
    await message.answer(
        t(lang, "freeform_guess", profile=title) + "\n\n" + t(lang, "q_target"),
        reply_markup=target_kb(lang),
    )


@on("callback_query", PageCb.filter())
async def on_page(cb: CallbackQuery, callback_data: PageCb, prefs: Prefs, store: DataStore) -> None:
    lang = _lang(prefs, cb)
    await cb.answer()  # first: Telegram expires unanswered queries
    snap = await store.get()
    if not snap or not isinstance(cb.message, Message):
        return
    result = compute(snap, callback_data.profile, callback_data.priority)
    target = None if callback_data.target == "-" else callback_data.target
    text, pages = render.ranking_page(result, lang, callback_data.page)
    text += render.stale_footer(snap, lang)
    page = min(callback_data.page, pages - 1)
    kb = result_kb(result, lang, target, page, pages, render.PAGE_SIZE)
    with contextlib.suppress(TelegramBadRequest):  # "message is not modified"
        await cb.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)


@on("callback_query", RefreshCb.filter())
async def on_refresh(
    cb: CallbackQuery, callback_data: RefreshCb, prefs: Prefs, store: DataStore
) -> None:
    """«🔄 Обновить»: the same pick (profile, priority, target) re-ranked on current data."""
    lang = _lang(prefs, cb)
    await cb.answer(t(lang, "refreshed"))
    if not isinstance(cb.message, Message):
        return
    target = None if callback_data.target == "-" else callback_data.target
    await send_ranking(
        cb.message,
        store,
        prefs,
        lang,
        cb.from_user.id,
        callback_data.profile,
        callback_data.priority,
        target,
        edit=True,
    )


@on("callback_query", MenuCb.filter())
async def on_menu(
    cb: CallbackQuery, callback_data: MenuCb, prefs: Prefs, store: DataStore, state: FSMContext
) -> None:
    lang = _lang(prefs, cb)
    await cb.answer()
    msg = cb.message if isinstance(cb.message, Message) else None
    if msg is None:
        return
    action = callback_data.action
    if action == "pick":
        await state.clear()
        await _show(msg, t(lang, "q_purpose"), purpose_kb(lang), edit=True)
    elif action == "top":
        await send_ranking(
            msg,
            store,
            prefs,
            lang,
            cb.from_user.id,
            TOP_PROFILE,
            Priority.QUALITY.value,
            None,
            edit=True,
        )
    elif action == "new":
        snap = await store.get()
        text = render.new_message(store.history, snap, lang) if snap else t(lang, "no_data")
        await _show(msg, text, menu_kb(lang), edit=True)
    else:  # home
        await state.clear()
        await _show(msg, t(lang, "start"), menu_kb(lang), edit=True)


async def _send_snippet(message: Message, model: Model, target: str, profile: str, lang: str):
    snippet = integrations.render(target, model.id, profile)
    await message.answer(
        render.snippet_message(snippet, model.id, lang),
        reply_markup=copy_kb(snippet, lang),
        disable_web_page_preview=True,
    )


async def _model_gone(message: Message, lang: str, profile: str, priority: str, target: str | None):
    """The button points at a model that has left the free list since it was shown."""
    kb = InlineKeyboardMarkup(inline_keyboard=[nav_row(lang, profile, priority, target)])
    await message.answer(t(lang, "model_gone"), reply_markup=kb)


def _last_priority(prefs: Prefs, user_id: int, profile: str) -> str:
    last = prefs.last_list.get(user_id)
    return last[1] if last and last[0] == profile else Priority.QUALITY.value


@on("callback_query", AddCb.filter())
async def on_add(cb: CallbackQuery, callback_data: AddCb, prefs: Prefs, store: DataStore) -> None:
    lang = _lang(prefs, cb)
    await cb.answer()  # first: Telegram expires unanswered queries
    if not isinstance(cb.message, Message):
        return
    snap = await store.get()
    model = find_by_key(snap, callback_data.key) if snap else None
    profile, target = callback_data.profile, callback_data.target
    if model is None:
        priority = _last_priority(prefs, cb.from_user.id, profile)
        await _model_gone(cb.message, lang, profile, priority, target)
        return
    prefs.last_model[cb.from_user.id] = model.id
    await _send_snippet(cb.message, model, target, profile, lang)


@on("message", Command("model"))
async def cmd_model(
    message: Message, command: CommandObject, prefs: Prefs, store: DataStore
) -> None:
    lang = _lang(prefs, message)
    snap = await store.get()
    if not snap:
        await message.answer(t(lang, "no_data"))
        return
    arg = (command.args or "").strip()
    if not arg:
        await message.answer(t(lang, "model_usage"))
        return
    found: tuple[int, Model] | None = None
    uid = message.from_user.id
    if arg.isdigit() and uid in prefs.last_list:
        profile, priority = prefs.last_list[uid]
        result = compute(snap, profile, priority)
        scored = next((s for s in result.all if s.rank == int(arg)), None)
        if scored:
            found = find_model(snap, scored.model.id)
    else:
        found = find_model(snap, arg)
    if not found:
        await message.answer(t(lang, "model_not_found", id=escape(arg)))
        return
    _, model = found
    prefs.last_model[uid] = model.id
    await message.answer(
        render.model_card(model, lang),
        reply_markup=card_kb(model.id, lang),
        disable_web_page_preview=True,
    )


@on("callback_query", CardCb.filter())
async def on_card(cb: CallbackQuery, callback_data: CardCb, prefs: Prefs, store: DataStore) -> None:
    lang = _lang(prefs, cb)
    await cb.answer()
    if not isinstance(cb.message, Message):
        return
    snap = await store.get()
    model = find_by_key(snap, callback_data.key) if snap else None
    profile, priority = prefs.last_list.get(cb.from_user.id, ("agent", Priority.QUALITY.value))
    if model is None:
        await _model_gone(cb.message, lang, profile, priority, callback_data.target)
        return
    await _send_snippet(cb.message, model, callback_data.target, profile, lang)


@on("message", Command("add"))
async def cmd_add(message: Message, prefs: Prefs, store: DataStore) -> None:
    lang = _lang(prefs, message)
    snap = await store.get()
    model_id = prefs.last_model.get(message.from_user.id)
    found = find_model(snap, model_id) if snap and model_id else None
    if not found:
        await message.answer(t(lang, "add_none"), reply_markup=menu_kb(lang))
        return
    _, model = found
    await message.answer(
        t(lang, "add_choose", id=escape(model.id)), reply_markup=card_kb(model.id, lang)
    )


@on("message", Command("new"))
async def cmd_new(message: Message, prefs: Prefs, store: DataStore) -> None:
    lang = _lang(prefs, message)
    snap = await store.get()
    if not snap:
        await message.answer(t(lang, "no_data"))
        return
    await message.answer(render.new_message(store.history, snap, lang), reply_markup=menu_kb(lang))
