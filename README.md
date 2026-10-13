# loosechange

> Бесплатные LLM с OpenRouter — отсортированные по силе, подобранные под вашу задачу и добавляемые в Hermes / VibeForge одной командой.

Open source (MIT), без монетизации.

## Что это
1. **Telegram-бот** — раз в несколько часов собирает список `:free` моделей OpenRouter, ранжирует по бенчмаркам, задаёт 2–3 уточняющих вопроса («для чего модель?») и выдаёт топ под задачу.
2. **CLI `loosechange`** — ставит выбранную модель в Hermes или VibeForge локально (бот не может писать на ваш диск, поэтому он отдаёт команду/конфиг-сниппет).
3. **Публичный снапшот** `data/models.json` (обновляется GitHub Action) — его читают бот, CLI и (позже) статичная веб-страница.

## Почему не Mini App
Бот + inline-кнопки закрывают весь сценарий (вопросы → список → сниппет). Mini App потребовал бы хостинг и фронтенд ради таблицы. Таблицу-лидерборд даём как **статическую страницу на GitHub Pages** из того же JSON (v2, ноль серверов). Подробно: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Документация
| Файл | Про что |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | компоненты, стек, структура репо, хостинг |
| [docs/RANKING.md](docs/RANKING.md) | источники бенчмарков, формула скоринга по профилям |
| [docs/DIALOG.md](docs/DIALOG.md) | сценарий бота, вопросы, команды |
| [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) | как добавить модель в Hermes и VibeForge |
| [docs/SECURITY.md](docs/SECURITY.md) | токены, лимиты, что не логируем |
| [docs/ROADMAP.md](docs/ROADMAP.md) | этапы и критерии готовности |
| [CLAUDE.md](CLAUDE.md) | правила для агента, разрабатывающего проект |
| [PROMPT_FOR_NEW_SESSION.md](PROMPT_FOR_NEW_SESSION.md) | промт для автономной сборки |

## Факты, проверенные 2026-10-13
- `GET https://openrouter.ai/api/v1/models` публичный, содержит `pricing`, `context_length`, `supported_parameters` и **встроенные бенчмарки** (`benchmarks.artificial_analysis`: intelligence/coding/agentic index; `benchmarks.design_arena`). Отдельный парсинг сторонних сайтов на старте не нужен.
- Бесплатных (prompt=0 и completion=0) моделей сейчас ~19 из 459; бенчмарки есть примерно у половины.
