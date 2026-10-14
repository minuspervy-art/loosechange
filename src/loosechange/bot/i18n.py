"""User-facing bot strings, RU (default) and EN."""

from __future__ import annotations

LANGS = ("ru", "en")
DEFAULT_LANG = "ru"

STRINGS: dict[str, dict[str, str]] = {
    "ru": {
        "start": (
            "👋 <b>loosechange</b> — бесплатные LLM с OpenRouter, отсортированные по "
            "бенчмаркам и подобранные под вашу задачу.\n\n"
            "/pick — подобрать модель (2–3 вопроса кнопками)\n"
            "/top — общий топ без вопросов\n"
            "/model &lt;id или номер&gt; — карточка модели\n"
            "/add — как добавить выбранную модель в Hermes / VibeForge\n"
            "/new — что появилось и исчезло за 7 дней\n"
            "/lang — English\n/about — о проекте"
        ),
        "about": (
            "<b>loosechange</b> — open source (MIT), без монетизации.\n"
            "Данные: OpenRouter <code>/api/v1/models</code> и встроенные бенчмарки "
            "Artificial Analysis / Design Arena. Модели без бенчмарков помечены "
            "«без бенчмарков» — оценки мы не выдумываем.\n"
            "Бот не просит и не хранит ваши ключи OpenRouter.\n"
            "Моделей в снапшоте: {count}, данные от {ts}."
        ),
        "q_purpose": "1/3 · <b>Для чего модель?</b>",
        "q_target": "2/3 · <b>Куда будете подключать?</b>",
        "q_priority": "3/3 · <b>Что важнее?</b>",
        "q_freeform": "Опишите задачу парой слов (например «пишу бота на Python»).",
        "freeform_guess": "Понял как: <b>{profile}</b>.",
        "p_agent": "🤖 Агент с инструментами",
        "p_coding": "💻 Код",
        "p_chat": "💬 Чат / общие вопросы",
        "p_reasoning": "🧮 Рассуждения / математика",
        "p_longctx": "📚 Длинные документы",
        "p_fast_cheap": "⚡ Быстро и дёшево",
        "p_design": "🎨 Дизайн / вёрстка",
        "p_unknown": "🤷 Не знаю",
        "t_hermes": "Hermes",
        "t_vibeforge": "VibeForge",
        "t_deepseek": "DeepSeek Harness",
        "t_other": "Другое",
        "ts_hermes": "Hermes",
        "ts_vibeforge": "VibeForge",
        "ts_deepseek": "DeepSeek",
        "ts_other": "Другое",
        "pr_quality": "🏆 Максимум качества",
        "pr_stability": "🛡 Стабильность (uptime)",
        "pr_context": "📏 Большой контекст",
        "top_header": "<b>Топ: {profile}</b> · приоритет: {priority}",
        "unrated_header": "<b>Без бенчмарков</b> (оценки нет — не выдумываем):",
        "no_models": "Подходящих бесплатных моделей сейчас нет.",
        "fast_unavailable": (
            "Профиль «Быстро и дёшево» сейчас недоступен: OpenRouter публично не отдаёт "
            "данные о скорости моделей. Показываю общий топ по интеллекту."
        ),
        "fallback_note": "по coding-индексу: нет данных Design Arena",
        "low_uptime": "⚠️ uptime {uptime:.0f}% за 30 мин",
        "expires": "⏳ бесплатно до {date} ({left})",
        "expires_soon": "⏳ скоро исчезнет: {date} ({left})",
        "left_days": "через {n} дн.",
        "left_today": "сегодня",
        "left_tomorrow": "завтра",
        "left_past": "срок прошёл",
        "ago_min": "{n} мин назад",
        "ago_h": "{n} ч назад",
        "ago_d": "{n} дн. назад",
        "about_fresh": "Список моделей обновлён {ago}.",
        "about_timers": (
            "Обновление по таймерам: список — каждые {list} мин, uptime — каждые {full} мин."
        ),
        "router": "🎲 роутер: случайная free-модель",
        "harness_only": "🔒 только Hermes / DeepSeek Harness",
        "hidden_harness": (
            "<i>Скрыто {n}: OpenRouter отдаёт их только агентным харнессам "
            "(Hermes, DeepSeek Harness) — в {target} будет 403.</i>"
        ),
        "harness_warn": (
            "⚠️ В {target} эта модель вернёт 403: OpenRouter отдаёт её только "
            "Hermes и DeepSeek Harness."
        ),
        "no_tools": "без tools",
        "unrated": "без бенчмарков",
        "show_all": "Показать все ({n})",
        "page": "Стр. {page}/{pages}",
        "add_btn": "🔧 #{rank} → {target}",
        "card_add": "🔧 {target}",
        "stale": "\n<i>данные от {ts}</i>",
        "model_usage": "Использование: /model &lt;id&gt; или /model &lt;номер из списка&gt;",
        "model_not_found": "Модель не найдена среди бесплатных: <code>{id}</code>",
        "add_none": "Сначала выберите модель: /pick, /top или /model &lt;id&gt;.",
        "add_choose": "Куда добавить <code>{id}</code>?",
        "snippet_header": "<b>{target}</b> · <code>{id}</code>",
        "snippet_cli": "Или локально одной командой:",
        "copy_cmd": "📋 Скопировать команду",
        "one_click": "⚡ Установить в один клик",
        "btn_menu": "🏠 Меню",
        "btn_refresh": "🔄 Обновить",
        "menu_pick": "🎯 Подобрать",
        "menu_top": "🏆 Топ",
        "menu_new": "🆕 Что нового",
        "refreshed": "Обновлено по свежим данным",
        "model_gone": (
            "Этой модели больше нет среди бесплатных — список обновился. "
            "Нажмите «🔄 Обновить», чтобы пересобрать подборку, или вернитесь в меню."
        ),
        "copy_id": "📋 Скопировать id модели",
        "need_key": (
            "Нужен ключ OpenRouter: https://openrouter.ai/keys — храните его только у себя."
        ),
        "new_header": "<b>За 7 дней</b>",
        "new_added": "➕ Новые: {ids}",
        "new_removed": "➖ Исчезли: {ids}",
        "new_none": "Изменений в списке бесплатных моделей не было.",
        "new_expiring": "⏳ Скоро исчезнут: {ids}",
        "lang_set": "Язык: русский.",
        "flood": "Не так быстро 🙂",
        "no_data": "Данные ещё не загружены, попробуйте через минуту.",
    },
    "en": {
        "start": (
            "👋 <b>loosechange</b> — free OpenRouter LLMs ranked by benchmarks and "
            "matched to your task.\n\n"
            "/pick — find a model (2–3 button questions)\n"
            "/top — overall top, no questions\n"
            "/model &lt;id or number&gt; — model card\n"
            "/add — how to add the chosen model to Hermes / VibeForge\n"
            "/new — added / removed in the last 7 days\n"
            "/lang — русский\n/about — about"
        ),
        "about": (
            "<b>loosechange</b> — open source (MIT), no monetization.\n"
            "Data: OpenRouter <code>/api/v1/models</code> with built-in Artificial "
            "Analysis / Design Arena benchmarks. Models without benchmarks are marked "
            "“unrated” — we never invent scores.\n"
            "The bot never asks for or stores your OpenRouter keys.\n"
            "Models in snapshot: {count}, data from {ts}."
        ),
        "q_purpose": "1/3 · <b>What is the model for?</b>",
        "q_target": "2/3 · <b>Where will you plug it in?</b>",
        "q_priority": "3/3 · <b>What matters most?</b>",
        "q_freeform": "Describe the task in a few words (e.g. “writing a Python bot”).",
        "freeform_guess": "Understood as: <b>{profile}</b>.",
        "p_agent": "🤖 Agent with tools",
        "p_coding": "💻 Coding",
        "p_chat": "💬 Chat / general",
        "p_reasoning": "🧮 Reasoning / math",
        "p_longctx": "📚 Long documents",
        "p_fast_cheap": "⚡ Fast & cheap",
        "p_design": "🎨 Design / web UI",
        "p_unknown": "🤷 Not sure",
        "t_hermes": "Hermes",
        "t_vibeforge": "VibeForge",
        "t_deepseek": "DeepSeek Harness",
        "t_other": "Other",
        "ts_hermes": "Hermes",
        "ts_vibeforge": "VibeForge",
        "ts_deepseek": "DeepSeek",
        "ts_other": "Other",
        "pr_quality": "🏆 Best quality",
        "pr_stability": "🛡 Stability (uptime)",
        "pr_context": "📏 Large context",
        "top_header": "<b>Top: {profile}</b> · priority: {priority}",
        "unrated_header": "<b>Unrated</b> (no benchmarks — no made-up scores):",
        "no_models": "No matching free models right now.",
        "fast_unavailable": (
            "“Fast & cheap” is unavailable: OpenRouter does not publish model speed "
            "data publicly. Showing the overall intelligence top instead."
        ),
        "fallback_note": "by coding index: no Design Arena data",
        "low_uptime": "⚠️ uptime {uptime:.0f}% over 30 min",
        "expires": "⏳ free until {date} ({left})",
        "expires_soon": "⏳ going away soon: {date} ({left})",
        "left_days": "in {n} days",
        "left_today": "today",
        "left_tomorrow": "tomorrow",
        "left_past": "date passed",
        "ago_min": "{n} min ago",
        "ago_h": "{n} h ago",
        "ago_d": "{n} days ago",
        "about_fresh": "Model list refreshed {ago}.",
        "about_timers": "Refresh timers: model list every {list} min, uptime every {full} min.",
        "router": "🎲 router: random free model",
        "harness_only": "🔒 Hermes / DeepSeek Harness only",
        "hidden_harness": (
            "<i>{n} hidden: OpenRouter serves them only to agentic harnesses "
            "(Hermes, DeepSeek Harness) — {target} would get 403.</i>"
        ),
        "harness_warn": (
            "⚠️ In {target} this model returns 403: OpenRouter serves it only to "
            "Hermes and DeepSeek Harness."
        ),
        "no_tools": "no tools",
        "unrated": "unrated",
        "show_all": "Show all ({n})",
        "page": "Page {page}/{pages}",
        "add_btn": "🔧 #{rank} → {target}",
        "card_add": "🔧 {target}",
        "stale": "\n<i>data from {ts}</i>",
        "model_usage": "Usage: /model &lt;id&gt; or /model &lt;number from the list&gt;",
        "model_not_found": "Not found among free models: <code>{id}</code>",
        "add_none": "Pick a model first: /pick, /top or /model &lt;id&gt;.",
        "add_choose": "Where to add <code>{id}</code>?",
        "snippet_header": "<b>{target}</b> · <code>{id}</code>",
        "snippet_cli": "Or locally with one command:",
        "copy_cmd": "📋 Copy command",
        "one_click": "⚡ Install in one click",
        "btn_menu": "🏠 Menu",
        "btn_refresh": "🔄 Refresh",
        "menu_pick": "🎯 Find a model",
        "menu_top": "🏆 Top",
        "menu_new": "🆕 What's new",
        "refreshed": "Refreshed with current data",
        "model_gone": (
            "This model is no longer free — the list has changed. "
            "Tap “🔄 Refresh” to rebuild the pick, or go back to the menu."
        ),
        "copy_id": "📋 Copy model id",
        "need_key": "You need an OpenRouter key: https://openrouter.ai/keys — keep it local.",
        "new_header": "<b>Last 7 days</b>",
        "new_added": "➕ Added: {ids}",
        "new_removed": "➖ Removed: {ids}",
        "new_none": "No changes in the free model list.",
        "new_expiring": "⏳ Going away soon: {ids}",
        "lang_set": "Language: English.",
        "flood": "Slow down 🙂",
        "no_data": "Data is not loaded yet, try again in a minute.",
    },
}


def t(lang: str, key: str, **kw) -> str:
    table = STRINGS.get(lang) or STRINGS[DEFAULT_LANG]
    text = table.get(key) or STRINGS[DEFAULT_LANG][key]
    return text.format(**kw) if kw else text
