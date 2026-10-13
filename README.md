# loosechange

> Бесплатные LLM с OpenRouter — отсортированные по силе, подобранные под вашу задачу и добавляемые в Hermes / VibeForge одной командой.

Open source (MIT), без монетизации.

## Что это
1. **Telegram-бот** — раз в несколько часов собирает список `:free` моделей OpenRouter, ранжирует по бенчмаркам, задаёт 2–3 уточняющих вопроса («для чего модель?») и выдаёт топ под задачу.
2. **CLI `loosechange`** — ставит выбранную модель в Hermes или VibeForge локально (бот не может писать на ваш диск, поэтому он отдаёт команду/конфиг-сниппет).
3. **Публичный снапшот** `data/models.json` (обновляется GitHub Action) — его читают бот, CLI и (позже) статичная веб-страница.

## Быстрый старт

### CLI: выбрать модель и добавить в Hermes
Пакет пока не опубликован на PyPI — запуск из git (после публикации будет просто `uvx loosechange …`):
```bash
uvx --from git+https://github.com/<you>/loosechange loosechange list --profile agent
```
```bash
uvx --from git+https://github.com/<you>/loosechange loosechange add thinkingmachines/inkling:free --to hermes
```
Без флагов `add` — это **dry-run**: печатает диф `~/.hermes/config.yaml`. Записать (с бэкапом `config.yaml.bak-<время>`):
```bash
uvx --from git+https://github.com/<you>/loosechange loosechange add thinkingmachines/inkling:free --to hermes --apply
```
Потом `hermes -m free-agent` (нужен `OPENROUTER_API_KEY` в `~/.hermes/.env`, ключ — https://openrouter.ai/keys). Ключ можно сразу взять из файла: `--key-file ~/or-key.txt` — он запишется в `~/.hermes/.env` с бэкапом и нигде не напечатается (другой уже записанный ключ заменяется только с `--replace-key`). Флаги: `--profile coding|chat|reasoning|longctx|design`, `--alias`, `--fallback` (добавить в цепочку fallback), `--force`, `--config`.
VibeForge: `… add <id> --to vibeforge` печатает инструкцию — автозаписи нет, см. [docs/guides/vibeforge-manual.md](docs/guides/vibeforge-manual.md). Любой другой OpenAI-совместимый клиент: `--to other`.

Профили: `agent` (tool-calling, ≥128k), `coding`, `chat`, `reasoning`, `longctx` (≥256k), `design`, `fast_cheap` (пока недоступен — OpenRouter не отдаёт скорость публично). Формулы — [docs/RANKING.md](docs/RANKING.md).

### Бот локально
```bash
uv sync
```
```bash
cp .env.example .env
```
Впишите `TELEGRAM_BOT_TOKEN` (от @BotFather) в `.env`, затем:
```bash
uv run loosechange collect
```
```bash
uv run loosechange-bot
```
Long-polling: домен, вебхук и открытые порты не нужны.

### Бот в Docker
```bash
docker build -t loosechange .
```
```bash
docker run -d --restart unless-stopped --env-file .env --name loosechange loosechange
```
В образе есть снапшот `data/models.json`; бот сам обновляет его каждые 3 ч (`LOOSECHANGE_SELF_COLLECT_HOURS`). Если репозиторий опубликован и Action обновляет JSON — задайте `LOOSECHANGE_DATA_URL=https://raw.githubusercontent.com/<you>/loosechange/main/data/models.json`.

### Данные по расписанию (GitHub Actions)
- `.github/workflows/collect.yml` — каждые 3 ч `loosechange collect` и коммит `data/` (только `GITHUB_TOKEN`, секреты бота в CI не нужны). Запуск вручную — `workflow_dispatch`.
- `.github/workflows/ci.yml` — ruff + pytest на push/PR.

### Разработка
```bash
uv run pytest -q
```
```bash
uv run ruff check . && uv run ruff format --check .
```
Самопроверка диалога бота без Telegram: `uv run python scripts/bot_selfcheck.py` → [docs/reports/bot-selfcheck.md](docs/reports/bot-selfcheck.md).

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
| [docs/guides/vibeforge-manual.md](docs/guides/vibeforge-manual.md) | ручное подключение модели в VibeForge |
| [docs/reports/bot-selfcheck.md](docs/reports/bot-selfcheck.md) | транскрипт самопроверки бота |
| [CLAUDE.md](CLAUDE.md) | правила для агента, разрабатывающего проект |
| [docs/agent/PROMPT_FOR_NEW_SESSION.md](docs/agent/PROMPT_FOR_NEW_SESSION.md) | промт для автономной сборки |

## Факты, проверенные 2026-10-13
- `GET https://openrouter.ai/api/v1/models` публичный, содержит `pricing`, `context_length`, `supported_parameters` и **встроенные бенчмарки** (`benchmarks.artificial_analysis`: intelligence/coding/agentic index; `benchmarks.design_arena`). Отдельный парсинг сторонних сайтов на старте не нужен.
- Бесплатных (prompt=0 и completion=0) моделей сейчас 19 из 459, из них 17 текстовых (2 — `lyria`, генерация музыки); бенчмарки есть у 11 из 17.
- Публичный `/models/{id}/endpoints` отдаёт uptime, но не latency/throughput (поэтому профиль `fast_cheap` пока выключен).
