"""Bot self-check: real updates through the aiogram dispatcher, Telegram API mocked."""

from datetime import UTC, datetime, timedelta
from itertools import count

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from loosechange.bot.dialog import MenuCb, PickCb, RefreshCb, guess_profile
from loosechange.bot.handlers import Prefs
from loosechange.bot.main import RedactFilter, build_dispatcher, load_dotenv
from loosechange.bot.render import fmt_ctx, split_message
from loosechange.bot.store import DataStore
from loosechange.core.collect import _dump, build_snapshot
from loosechange.core.schema import History, HistoryEvent

_ids = count(1)


class RecordingSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list = []

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, SendMessage):
            return Message(
                message_id=next(_ids),
                date=datetime.now(UTC),
                chat=Chat(id=method.chat_id, type="private"),
                text=method.text,
            )
        return True

    async def stream_content(self, *a, **kw):  # pragma: no cover
        yield b""

    async def close(self) -> None:
        pass

    def sent(self, kind=SendMessage):
        return [c for c in self.calls if isinstance(c, kind)]

    def texts(self):
        return [c.text for c in self.calls if isinstance(c, SendMessage | EditMessageText)]


NOW = datetime.now(UTC)


@pytest.fixture
def env(tmp_path, raw_models):
    snap = build_snapshot(raw_models, now=NOW)
    _dump(tmp_path / "models.json", snap)
    hist = History(events=[HistoryEvent(ts=NOW - timedelta(days=1), added=["a/new:free"])])
    _dump(tmp_path / "history" / "changes.json", hist)
    store = DataStore(path=tmp_path / "models.json")
    prefs = Prefs()
    dp = build_dispatcher(store, prefs, flood_interval=0)
    session = RecordingSession()
    bot = Bot("42:TEST", session=session, default=None)
    return dp, bot, session, store, prefs


def user(uid=7, lang="ru"):
    return User(id=uid, is_bot=False, first_name="T", language_code=lang)


def msg_update(text, uid=7, lang="ru"):
    m = Message(
        message_id=next(_ids),
        date=datetime.now(UTC),
        chat=Chat(id=uid, type="private"),
        from_user=user(uid, lang),
        text=text,
    )
    return Update(update_id=next(_ids), message=m)


def cb_update(data, uid=7, lang="ru"):
    m = Message(
        message_id=next(_ids),
        date=datetime.now(UTC),
        chat=Chat(id=uid, type="private"),
        text="prev",
    )
    cb = CallbackQuery(
        id=str(next(_ids)), from_user=user(uid, lang), chat_instance="ci", data=data, message=m
    )
    return Update(update_id=next(_ids), callback_query=cb)


async def feed(env, upd):
    dp, bot, *_ = env
    await dp.feed_update(bot, upd)


def buttons(method):
    kb = method.reply_markup
    return [b for row in kb.inline_keyboard for b in row] if kb else []


async def test_start_ru_and_en(env):
    _, _, session, *_ = env
    await feed(env, msg_update("/start"))
    await feed(env, msg_update("/start", uid=8, lang="en"))
    ru, en = session.texts()
    assert "Подобрать" in ru or "подобрать" in ru
    assert "find a model" in en


async def test_top_lists_rated_then_unrated(env):
    _, _, session, *_ = env
    await feed(env, msg_update("/top"))
    [sent] = session.sent()
    assert "Топ" in sent.text
    assert "inclusionai/ling-3.1-flash" in sent.text  # #1 by intelligence
    labels = [b.text for b in buttons(sent)]
    assert any("Hermes" in t for t in labels)
    assert any("Показать все" in t for t in labels)
    for b in buttons(sent):
        assert len(b.callback_data.encode()) <= 64


async def test_pick_full_dialog_and_snippet(env):
    _, _, session, store, prefs = env
    await feed(env, msg_update("/pick"))
    assert "Для чего" in session.texts()[-1]
    await feed(env, cb_update(PickCb(step="purpose", value="agent").pack()))
    assert "Куда" in session.texts()[-1]
    await feed(env, cb_update(PickCb(step="target", value="hermes").pack()))
    assert "важнее" in session.texts()[-1]
    calls_before = len(session.calls)
    await feed(env, cb_update(PickCb(step="priority", value="quality").pack()))
    # the question message itself becomes the result: answer + edit, no extra message
    assert [type(c).__name__ for c in session.calls[calls_before:]] == [
        "AnswerCallbackQuery",
        "EditMessageText",
    ]
    result = session.sent(EditMessageText)[-1]
    assert "Агент" in result.text
    add_buttons = [b for b in buttons(result) if b.callback_data.startswith("a:")]
    assert add_buttons and all("Hermes" in b.text for b in add_buttons)
    assert prefs.last_list[7] == ("agent", "quality")

    await feed(env, cb_update(add_buttons[0].callback_data))
    snippet = session.sent()[-1].text
    assert "model_aliases:" in snippet
    assert "free-agent:" in snippet
    assert "provider: openrouter" in snippet
    assert "loosechange add" in snippet


async def test_pick_preselected_skips_questions(env):
    _, _, session, *_ = env
    await feed(env, msg_update("/pick coding vibeforge"))
    assert "важнее" in session.texts()[-1]
    await feed(env, cb_update(PickCb(step="priority", value="stability").pack()))
    result = session.sent(EditMessageText)[-1]
    assert "Код" in result.text
    assert all("VibeForge" in b.text for b in buttons(result) if b.callback_data.startswith("a:"))


async def test_pick_freeform(env):
    _, _, session, *_ = env
    await feed(env, msg_update("/pick"))
    await feed(env, cb_update(PickCb(step="purpose", value="unknown").pack()))
    assert "Опишите" in session.texts()[-1]
    await feed(env, msg_update("пишу скрипт на python"))
    assert "Код" in session.texts()[-1]


async def test_fast_cheap_falls_back_with_notice(env):
    _, _, session, *_ = env
    await feed(env, msg_update("/pick fast_cheap other"))
    await feed(env, cb_update(PickCb(step="priority", value="quality").pack()))
    texts = session.texts()
    assert any("недоступен" in t for t in texts)
    assert "Чат" in texts[-1]


async def test_model_card_and_add(env):
    _, _, session, *_ = env
    await feed(env, msg_update("/model thinkingmachines/inkling"))  # ':free' auto-appended
    card = session.sent()[-1]
    assert "Inkling" in card.text and "openrouter.ai/thinkingmachines/inkling:free" in card.text
    [hermes_btn] = [b for b in buttons(card) if "Hermes" in b.text]
    await feed(env, cb_update(hermes_btn.callback_data))
    assert "model_aliases:" in session.sent()[-1].text

    await feed(env, msg_update("/add"))
    assert "Куда добавить" in session.sent()[-1].text

    await feed(env, msg_update("/model nope/nope"))
    assert "не найдена" in session.sent()[-1].text
    await feed(env, msg_update("/model"))
    assert "/model" in session.sent()[-1].text


async def test_model_by_number_after_top(env):
    _, _, session, *_ = env
    await feed(env, msg_update("/top"))
    await feed(env, msg_update("/model 1"))
    assert "Ling 3.1 Flash" in session.sent()[-1].text


async def test_add_without_selection(env):
    _, _, session, *_ = env
    await feed(env, msg_update("/add", uid=99))
    assert "Сначала" in session.sent()[-1].text


async def test_add_buttons_survive_data_refresh(env, raw_models):
    _, _, session, store, _ = env
    await feed(env, msg_update("/top"))
    add = next(b for b in buttons(session.sent()[-1]) if b.callback_data.startswith("a:"))
    # the timed refresh rewrites the snapshot (new generated_at) — the button still works
    _dump(store.path, build_snapshot(raw_models, now=NOW + timedelta(minutes=15)))
    await feed(env, cb_update(add.callback_data))
    assert "model_aliases:" in session.sent()[-1].text


async def test_gone_model_offers_menu_and_refresh(env, raw_models):
    _, _, session, store, _ = env
    await feed(env, msg_update("/pick chat hermes"))
    await feed(env, cb_update(PickCb(step="priority", value="stability").pack()))
    result = session.sent(EditMessageText)[-1]
    add = next(b for b in buttons(result) if b.callback_data.startswith("a:"))
    top_id = "inclusionai/ling-3.1-flash"
    assert top_id in result.text
    # the #1 model stops being free between showing the list and the tap
    _dump(store.path, build_snapshot([m for m in raw_models if m["id"] != top_id], now=NOW))
    await feed(env, cb_update(add.callback_data))
    gone = session.sent()[-1]
    assert "больше нет среди бесплатных" in gone.text
    [menu, refresh] = buttons(gone)
    assert menu.text == "🏠 Меню" and refresh.text == "🔄 Обновить"
    assert (
        refresh.callback_data
        == RefreshCb(profile="chat", priority="stability", target="hermes").pack()
    )
    # «Обновить» re-ranks the same pick in place, without the gone model
    await feed(env, cb_update(refresh.callback_data))
    refreshed = session.sent(EditMessageText)[-1]
    assert "Чат" in refreshed.text and top_id not in refreshed.text
    assert session.sent(AnswerCallbackQuery)[-1].text == "Обновлено по свежим данным"


async def test_result_has_menu_and_refresh_row(env):
    _, _, session, *_ = env
    await feed(env, msg_update("/top"))
    rows = session.sent()[-1].reply_markup.inline_keyboard
    assert [b.text for b in rows[-1]] == ["🏠 Меню", "🔄 Обновить"]
    for row in rows:
        for b in row:
            assert len(b.callback_data.encode()) <= 64


async def test_menu_actions(env):
    _, _, session, *_ = env
    await feed(env, cb_update(MenuCb(action="home").pack()))
    home = session.sent(EditMessageText)[-1]
    assert "/pick" in home.text
    assert [b.text for b in buttons(home)] == ["🎯 Подобрать", "🏆 Топ", "🆕 Что нового"]
    await feed(env, cb_update(MenuCb(action="pick").pack()))
    assert "Для чего" in session.sent(EditMessageText)[-1].text
    await feed(env, cb_update(MenuCb(action="top").pack()))
    assert "Топ" in session.sent(EditMessageText)[-1].text
    await feed(env, cb_update(MenuCb(action="new").pack()))
    assert "За 7 дней" in session.sent(EditMessageText)[-1].text


async def test_refresh_unchanged_does_not_duplicate(env):
    from aiogram.exceptions import TelegramBadRequest

    _, bot, session, *_ = env

    async def not_modified(bot_, method, timeout=None):
        session.calls.append(method)
        if isinstance(method, EditMessageText):
            raise TelegramBadRequest(method=method, message="Bad Request: message is not modified")
        return True

    session.make_request = not_modified
    data = RefreshCb(profile="chat", priority="quality", target="-").pack()
    await feed(env, cb_update(data))
    assert not session.sent(SendMessage)  # no duplicate message when nothing changed


async def test_lost_dialog_state_restarts_pick(env):
    _, _, session, *_ = env
    await feed(env, cb_update(PickCb(step="priority", value="quality").pack()))
    assert "Для чего" in session.sent(EditMessageText)[-1].text


async def test_new_and_about_and_lang(env):
    _, _, session, *_ = env
    await feed(env, msg_update("/new"))
    assert "a/new:free" in session.sent()[-1].text
    await feed(env, msg_update("/about"))
    assert "MIT" in session.sent()[-1].text
    await feed(env, msg_update("/lang"))
    await feed(env, cb_update("l:en"))
    await feed(env, msg_update("/top"))
    assert "Top:" in session.sent()[-1].text


async def test_pagination(env):
    _, _, session, *_ = env
    await feed(env, msg_update("/top"))
    show_all = next(b for b in buttons(session.sent()[-1]) if b.callback_data.startswith("g:"))
    await feed(env, cb_update(show_all.callback_data))
    edit = session.sent(EditMessageText)[-1]
    assert "Стр. 2/" in edit.text


async def test_antiflood(raw_models, tmp_path):
    _dump(tmp_path / "models.json", build_snapshot(raw_models, now=NOW))
    dp = build_dispatcher(DataStore(path=tmp_path / "models.json"), Prefs(), flood_interval=2)
    session = RecordingSession()
    bot = Bot("42:TEST", session=session)
    await dp.feed_update(bot, msg_update("/start", uid=5))
    await dp.feed_update(bot, msg_update("/start", uid=5))
    await dp.feed_update(bot, msg_update("/start", uid=6))
    assert len(session.sent()) == 2


def test_html_is_escaped(raw_models):
    from loosechange.bot.render import model_card

    m = build_snapshot(raw_models, now=NOW).models[0].model_copy(update={"name": "<b>x</b>&"})
    assert "&lt;b&gt;x&lt;/b&gt;&amp;" in model_card(m, "ru")


def test_split_message():
    text = "\n".join("x" * 100 for _ in range(100))
    parts = split_message(text, 1000)
    assert all(len(p) <= 1000 for p in parts)
    assert "\n".join(parts) == text


def test_fmt_ctx():
    assert fmt_ctx(1_048_576) == "1M"
    assert fmt_ctx(262_144) == "256k"
    assert fmt_ctx(128_000) == "128k"
    assert fmt_ctx(512) == "512"


@pytest.mark.parametrize(
    "text,profile",
    [
        ("сверстать лендинг", "design"),
        ("агент для hermes", "agent"),
        ("разобрать длинный pdf договор", "longctx"),
        ("задачи по математике", "reasoning"),
        ("саммари писем", "fast_cheap"),
        ("пишу бота на python", "coding"),
        ("просто поболтать", "chat"),
        ("fix a bug in my code", "coding"),
    ],
)
def test_guess_profile(text, profile):
    assert guess_profile(text) == profile


def test_redact_filter():
    import logging

    rec = logging.LogRecord("x", logging.INFO, "f", 1, "url /bot%s/getMe", ("SECRET",), None)
    RedactFilter("SECRET").filter(rec)
    assert "SECRET" not in rec.getMessage()


def test_load_dotenv(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("# c\nLC_TEST_A=1\nLC_TEST_B=\nLC_TEST_C='q'\n")
    monkeypatch.delenv("LC_TEST_A", raising=False)
    monkeypatch.delenv("LC_TEST_B", raising=False)
    monkeypatch.delenv("LC_TEST_C", raising=False)
    load_dotenv(f)
    import os

    assert os.environ["LC_TEST_A"] == "1"
    assert "LC_TEST_B" not in os.environ
    assert os.environ["LC_TEST_C"] == "q"


async def test_unauthorized_token_gives_clear_error(monkeypatch, tmp_path):
    from aiogram.exceptions import TelegramUnauthorizedError
    from aiogram.methods import GetMe

    import loosechange.bot.main as bm

    closed = []

    class FakeBot:
        def __init__(self, *a, **kw):
            self.session = self

        async def get_me(self):
            raise TelegramUnauthorizedError(method=GetMe(), message="Unauthorized")

        async def close(self):
            closed.append(True)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1:bad")
    monkeypatch.setattr(bm, "Bot", FakeBot)
    with pytest.raises(SystemExit, match="Unauthorized"):
        await bm.run()
    assert closed  # aiohttp session is closed even on failure


async def test_snippet_has_one_tap_copy_button(env):
    _, _, session, *_ = env
    await feed(env, msg_update("/pick agent hermes"))
    await feed(env, cb_update(PickCb(step="priority", value="quality").pack()))
    result = session.sent(EditMessageText)[-1]
    add = next(b for b in buttons(result) if b.callback_data.startswith("a:"))
    await feed(env, cb_update(add.callback_data))
    snippet = session.sent()[-1]
    [copy, menu] = buttons(snippet)
    assert menu.text == "🏠 Меню"
    assert copy.text == "📋 Скопировать команду"
    assert copy.copy_text.text.endswith("--to hermes --profile agent --apply")
    assert copy.copy_text.text in snippet.text  # the same command is shown in the message


async def test_vibeforge_copy_button_copies_model_id(env):
    _, _, session, *_ = env
    await feed(env, msg_update("/model thinkingmachines/inkling:free"))
    vf = next(b for b in buttons(session.sent()[-1]) if "VibeForge" in b.text)
    await feed(env, cb_update(vf.callback_data))
    [copy, _menu] = buttons(session.sent()[-1])
    assert copy.text == "📋 Скопировать id модели"
    assert copy.copy_text.text == "thinkingmachines/inkling:free"


def test_copy_kb_respects_telegram_limit():
    from loosechange.bot.dialog import copy_kb
    from loosechange.integrations import Snippet

    s = Snippet(target="hermes", language="text", body="", command="x" * 300, copy_text="x" * 300)
    kb = copy_kb(s, "ru")
    assert [b.text for row in kb.inline_keyboard for b in row] == ["🏠 Меню"]  # no copy button


def test_expiry_countdown():
    from datetime import date

    from loosechange.bot.render import ago, time_left

    today = date(2026, 10, 13)
    assert time_left("ru", date(2026, 10, 31), today) == "через 18 дн."
    assert time_left("ru", date(2026, 10, 14), today) == "завтра"
    assert time_left("ru", today, today) == "сегодня"
    assert time_left("en", date(2026, 10, 1), today) == "date passed"
    assert ago("ru", NOW - timedelta(minutes=7), NOW) == "7 мин назад"
    assert ago("en", NOW - timedelta(hours=3), NOW) == "3 h ago"


def test_card_shows_countdown(raw_models):
    from datetime import date

    from loosechange.bot.render import model_card

    snap = build_snapshot(raw_models, now=NOW)
    m = snap.get("poolside/laguna-s-2.1:free")
    assert m.expiration_date == date(2026, 10, 31)
    card = model_card(m, "ru", today=date(2026, 10, 13))
    assert "бесплатно до 2026-10-31 (через 18 дн.)" in card
    card = model_card(m, "ru", today=date(2026, 10, 28))
    assert "скоро исчезнет: 2026-10-31 (через 3 дн.)" in card


async def test_about_shows_refresh_timers(raw_models, tmp_path):
    from loosechange.core.refresh import Refresher, RefreshPolicy

    _dump(tmp_path / "models.json", build_snapshot(raw_models, now=NOW))
    store = DataStore(
        path=tmp_path / "models.json",
        refresher=Refresher(
            tmp_path, RefreshPolicy.from_minutes(15, 60), quick=lambda d: None, full=lambda d: None
        ),
    )
    dp = build_dispatcher(store, Prefs(), flood_interval=0)
    session = RecordingSession()
    await dp.feed_update(Bot("42:TEST", session=session), msg_update("/about"))
    text = session.sent()[-1].text
    assert "каждые 15 мин" in text and "каждые 60 мин" in text
    assert "мин назад" in text


def test_refresh_policy_from_env(monkeypatch):
    from datetime import timedelta as td

    from loosechange.bot.main import refresh_policy_from_env

    for k in (
        "LOOSECHANGE_REFRESH_MINUTES",
        "LOOSECHANGE_FULL_REFRESH_MINUTES",
        "LOOSECHANGE_SELF_COLLECT_HOURS",
    ):
        monkeypatch.delenv(k, raising=False)
    p = refresh_policy_from_env()
    assert (p.list_ttl, p.full_ttl) == (td(minutes=15), td(minutes=60))
    monkeypatch.setenv("LOOSECHANGE_SELF_COLLECT_HOURS", "3")
    assert refresh_policy_from_env().full_ttl == td(hours=3)
    monkeypatch.setenv("LOOSECHANGE_REFRESH_MINUTES", "10")
    monkeypatch.setenv("LOOSECHANGE_FULL_REFRESH_MINUTES", "oops")
    p = refresh_policy_from_env()
    assert p.list_ttl == td(minutes=10) and p.full_ttl == td(hours=3)


async def test_vibeforge_snippet_has_no_terminal_command(env):
    _, _, session, *_ = env
    await feed(env, msg_update("/model thinkingmachines/inkling-small:free"))
    vf = next(b for b in buttons(session.sent()[-1]) if "VibeForge" in b.text)
    await feed(env, cb_update(vf.callback_data))
    text = session.sent()[-1].text
    assert "loosechange add" not in text and "Provider: OpenRouter" in text
