"""Bot entry point: long-polling, no webhook/domain needed.

Env (see .env.example and docs/ARCHITECTURE.md): TELEGRAM_BOT_TOKEN (required),
LOOSECHANGE_DATA (path, default data/models.json), LOOSECHANGE_DATA_URL (raw GitHub
URL, overrides the path), LOOSECHANGE_REFRESH_MINUTES / LOOSECHANGE_FULL_REFRESH_MINUTES
(expiry timers of the model list / uptime; 0 disables).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from ..core.collect import load_snapshot
from ..core.refresh import Refresher, RefreshPolicy
from .handlers import AntiFlood, Prefs, build_router
from .store import DataStore

log = logging.getLogger("loosechange.bot")

COMMANDS = {
    "ru": [
        ("pick", "Подобрать модель под задачу"),
        ("top", "Общий топ бесплатных моделей"),
        ("model", "Карточка модели"),
        ("add", "Добавить в Hermes / VibeForge"),
        ("new", "Что нового за 7 дней"),
        ("lang", "Язык / Language"),
        ("about", "О проекте"),
    ],
    "en": [
        ("pick", "Find a model for your task"),
        ("top", "Overall top of free models"),
        ("model", "Model card"),
        ("add", "Add to Hermes / VibeForge"),
        ("new", "What's new in 7 days"),
        ("lang", "Language / Язык"),
        ("about", "About"),
    ],
}


def load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env loader; existing environment variables win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if value:
            os.environ.setdefault(key.strip(), value)


class RedactFilter(logging.Filter):
    """Defense in depth: never let the bot token reach a log line."""

    def __init__(self, secret: str) -> None:
        super().__init__()
        self.secret = secret

    def filter(self, record: logging.LogRecord) -> bool:
        if self.secret and self.secret in record.getMessage():
            record.msg = record.getMessage().replace(self.secret, "<token>")
            record.args = None
        return True


def setup_logging(token: str) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    for handler in logging.getLogger().handlers:
        handler.addFilter(RedactFilter(token))


def refresh_policy_from_env() -> RefreshPolicy:
    def minutes(name: str, default: float) -> float:
        raw = os.environ.get(name, "").strip()
        try:
            return float(raw) if raw else default
        except ValueError:
            log.warning("%s=%r is not a number; using %s", name, raw, default)
            return default

    full_default = 60.0
    legacy_hours = os.environ.get("LOOSECHANGE_SELF_COLLECT_HOURS", "").strip()
    if legacy_hours:  # backward compatibility with the first release
        full_default = minutes("LOOSECHANGE_SELF_COLLECT_HOURS", 1.0) * 60
    return RefreshPolicy.from_minutes(
        minutes("LOOSECHANGE_REFRESH_MINUTES", 15.0),
        minutes("LOOSECHANGE_FULL_REFRESH_MINUTES", full_default),
    )


def build_dispatcher(
    store: DataStore, prefs: Prefs | None = None, flood_interval: float = 2.0
) -> Dispatcher:
    prefs = prefs or Prefs()
    dp = Dispatcher(storage=MemoryStorage())
    dp["store"] = store
    dp["prefs"] = prefs
    flood = AntiFlood(flood_interval, prefs)
    dp.message.outer_middleware(flood)
    dp.callback_query.outer_middleware(flood)
    dp.include_router(build_router())
    return dp


async def run() -> None:
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set (put it into .env)")
    setup_logging(token)

    data_path = Path(os.environ.get("LOOSECHANGE_DATA", "data/models.json"))
    url = os.environ.get("LOOSECHANGE_DATA_URL") or None
    refresher = None
    if not url:
        policy = refresh_policy_from_env()
        if policy.enabled:
            refresher = Refresher(data_path.parent, policy)
    store = DataStore(path=data_path, url=url, refresher=refresher)
    dp = build_dispatcher(store)

    bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    tasks: list[asyncio.Task] = []
    try:
        try:
            me = await bot.get_me()
        except TelegramUnauthorizedError:
            raise SystemExit(
                "Telegram rejected TELEGRAM_BOT_TOKEN (Unauthorized): the token is wrong or "
                "was revoked/reissued in @BotFather — put the current token into .env"
            ) from None
        for lang, cmds in COMMANDS.items():
            await bot.set_my_commands(
                [BotCommand(command=c, description=d) for c, d in cmds],
                language_code=None if lang == "ru" else lang,
            )
        await bot.delete_webhook(drop_pending_updates=False)

        if refresher:
            p = refresher.policy
            log.info(
                "data refresh timers: list every %s, uptime every %s",
                p.list_ttl or "off",
                p.full_ttl or "off",
            )
            tasks.append(asyncio.create_task(refresher.loop(lambda: load_snapshot(data_path))))
        log.info("starting long-polling as @%s", me.username)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await bot.session.close()


def main() -> None:  # pragma: no cover
    asyncio.run(run())


if __name__ == "__main__":  # pragma: no cover
    main()
