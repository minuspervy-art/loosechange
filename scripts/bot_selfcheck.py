"""Replay a scripted conversation through the real dispatcher (Telegram API mocked)
and write the bot's answers to docs/reports/bot-selfcheck.md.

    uv run python scripts/bot_selfcheck.py
"""

from __future__ import annotations

import asyncio
import html
import re
import sys
from datetime import UTC, datetime
from itertools import count
from pathlib import Path

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from loosechange.bot.dialog import PickCb
from loosechange.bot.handlers import Prefs
from loosechange.bot.main import build_dispatcher
from loosechange.bot.store import DataStore

ROOT = Path(__file__).resolve().parent.parent
_ids = count(1)


class Recorder(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.out: list = []

    async def make_request(self, bot, method, timeout=None):
        self.out.append(method)
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


USER = User(id=1, is_bot=False, first_name="Tester", language_code="ru")


def message(text: str) -> Update:
    return Update(
        update_id=next(_ids),
        message=Message(
            message_id=next(_ids),
            date=datetime.now(UTC),
            chat=Chat(id=1, type="private"),
            from_user=USER,
            text=text,
        ),
    )


def callback(data: str) -> Update:
    m = Message(
        message_id=next(_ids), date=datetime.now(UTC), chat=Chat(id=1, type="private"), text="…"
    )
    return Update(
        update_id=next(_ids),
        callback_query=CallbackQuery(
            id=str(next(_ids)), from_user=USER, chat_instance="c", data=data, message=m
        ),
    )


def strip_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def describe(method) -> str:
    if isinstance(method, SendMessage | EditMessageText):
        kind = "send" if isinstance(method, SendMessage) else "edit"
        lines = [f"**bot ({kind}):**", "```", strip_html(method.text), "```"]
        kb = method.reply_markup
        if kb:
            rows = [" | ".join(f"[{b.text}]" for b in row) for row in kb.inline_keyboard]
            lines.append("кнопки: " + " / ".join(rows))
        return "\n".join(lines)
    if isinstance(method, AnswerCallbackQuery) and method.text:
        return f"**bot (toast):** {method.text}"
    return ""


async def main() -> None:
    store = DataStore(path=ROOT / "data" / "models.json")
    dp = build_dispatcher(store, Prefs(), flood_interval=0)
    rec = Recorder()
    bot = Bot("1:SELFCHECK", session=rec)
    script: list[tuple[str, str]] = [
        ("msg", "/start"),
        ("msg", "/top"),
        ("msg", "/pick"),
        ("cb", PickCb(step="purpose", value="agent").pack()),
        ("cb", PickCb(step="target", value="hermes").pack()),
        ("cb", PickCb(step="priority", value="quality").pack()),
        ("first_add", ""),
        ("msg", "/model thinkingmachines/inkling:free"),
        ("msg", "/new"),
    ]
    out = [
        "# Самопроверка бота",
        "",
        f"Сгенерировано `scripts/bot_selfcheck.py` {datetime.now(UTC):%Y-%m-%d %H:%M} UTC "
        "на `data/models.json`: реальные handlers и диспетчер aiogram, Telegram API "
        "подменён записывающей сессией. Это не заменяет ручной прогон в Telegram.",
        "",
    ]
    last_kb = None
    for kind, payload in script:
        if kind == "first_add":
            btn = next(
                b
                for row in last_kb.inline_keyboard
                for b in row
                if b.callback_data.startswith("a:")
            )
            kind, payload = "cb", btn.callback_data
            out.append(f"**user:** нажимает «{btn.text}»")
        elif kind == "msg":
            out.append(f"**user:** `{payload}`")
        else:
            out.append(f"**user:** нажимает кнопку `{payload}`")
        start = len(rec.out)
        await dp.feed_update(bot, message(payload) if kind == "msg" else callback(payload))
        for m in rec.out[start:]:
            d = describe(m)
            if d:
                out.append(d)
            if getattr(m, "reply_markup", None):
                last_kb = m.reply_markup
        out.append("")
    target = ROOT / "docs" / "reports" / "bot-selfcheck.md"
    target.write_text("\n".join(out) + "\n")
    print(f"wrote {target.relative_to(ROOT)} ({len(rec.out)} API calls)", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
