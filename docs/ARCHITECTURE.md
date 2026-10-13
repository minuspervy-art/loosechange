# Архитектура

## Решение: бот + CLI + статический JSON
```
GitHub Action (cron 3ч)         ┌── bot (aiogram) ── Telegram
  collector ──► data/models.json┤
  (OR API + enrichers)          ├── CLI loosechange (add/list/pick)
                                └── site/ (GitHub Pages, v2)
```
- **Collector** — Python-модуль `loosechange.core.collect`: тянет OpenRouter `/models`, фильтрует `:free`, нормализует, мерджит бенчмарки, пишет `data/models.json` + `data/history/` (дифф: новые/исчезнувшие модели).
- **Ranker** — чистые функции `rank(models, profile) -> list[Scored]` ([RANKING.md](RANKING.md)). Без сети, полностью тестируемо.
- **Bot** — aiogram 3, long-polling (без вебхука и домена). Читает JSON с диска/из raw GitHub, кеш в памяти. Состояние диалога — in-memory FSM (потеря при рестарте допустима).
- **CLI** — `pipx install loosechange` / `uvx loosechange`. Команды: `list --profile coding`, `add <model-id> --to hermes|vibeforge [--dry-run]`.
- **Integrations** — адаптеры `integrations/hermes.py`, `integrations/vibeforge.py` с общим интерфейсом `render(model) -> Snippet` и `apply(model, dry_run)`.

## Collector и схема `data/models.json` (этап 1, реализовано)
Запуск: `loosechange collect` (или `uv run python -m loosechange.core.collect`). Схема — pydantic `Snapshot` в `src/loosechange/core/schema.py`, `schema_version: 1`:
- `generated_at`, `source`, `total_models` (все модели OR), `models[]`, `excluded[]` (бесплатные, но не текстовые — с причиной).
- `models[]`: `id`, `name`, `description` (≤300 симв.), `context_length`, `max_completion_tokens`, модальности, `supported_parameters`, `expiration_date`, `is_free_variant` (`:free`), `is_router` (`openrouter/*`), `benchmarks` (`intelligence`/`coding`/`agentic` как есть из OR, `null` если нет; `design_arena[]` целиком), `reliability` (лучший провайдер из `/endpoints`: `uptime_30m`, `uptime_1d`, `latency_30m`, `throughput_30m`, `providers`), `first_seen`.
- `data/history/changes.json` — события `{ts, added[], removed[]}` между снапшотами, хранится 90 дней (для `/new`).
- `/endpoints` запрашивается по каждой free-модели (~17 запросов); ошибка одного запроса → у модели просто нет `reliability`.

Факт 2026-10-13: публичный `/endpoints` отдаёт `uptime_*`, но `latency_last_30m`/`throughput_last_30m` = `null` у всех free-моделей.

## Запуск бота (этап 3)
`uv run loosechange-bot` (или `python -m loosechange.bot`). Переменные окружения (`.env` читается автоматически, переменные окружения важнее):
| Переменная | Назначение |
|---|---|
| `TELEGRAM_BOT_TOKEN` | обязательно |
| `LOOSECHANGE_DATA` | путь к снапшоту, по умолчанию `data/models.json` (перечитывается при изменении mtime) |
| `LOOSECHANGE_DATA_URL` | raw-URL снапшота в GitHub; если задан — бот читает его раз в 10 мин, путь игнорируется |
| `LOOSECHANGE_REFRESH_MINUTES` | TTL списка моделей, по умолчанию `15`; `0` — выкл. (см. «Обновление данных») |
| `LOOSECHANGE_FULL_REFRESH_MINUTES` | TTL uptime (полный сбор с `/endpoints`), по умолчанию `60`; `0` — выкл. |
| `LOOSECHANGE_SELF_COLLECT_HOURS` | устаревшее (первый релиз): если задано — задаёт TTL uptime в часах |
| `LOOSECHANGE_CLI` | префикс команды в сниппетах и кнопке «Скопировать команду», по умолчанию `uvx loosechange`; локально удобно `uv run --project <путь к репо> loosechange` |
Токен дополнительно вырезается из любых строк логов (`RedactFilter`), логгер httpx приглушён до WARNING.

## Обновление данных (таймеры истечения)
Free-модели OpenRouter появляются и исчезают за дни, поэтому бот держит локальный снапшот свежим сам (`core/refresh.py`, если не задан `LOOSECHANGE_DATA_URL`). Два таймера считаются от меток внутри снапшота, поэтому переживают рестарт и сон ноутбука:
| Таймер | По умолчанию | Что делает | Цена |
|---|---|---|---|
| список (`generated_at` + TTL) | 15 мин | `quick_collect`: только `GET /models` — ловит новые/исчезнувшие модели; uptime известных моделей переносится из прошлого снапшота | 1 запрос, ~1 с |
| uptime (`reliability_at` + TTL) | 60 мин | `collect`: `/models` + `/endpoints` каждой free-модели | ~18 запросов, 5–15 с |
- **Перед ответом пользователю** (`DataStore.get` → `Refresher.kick`) бот **никогда не ждёт сеть**: если таймер истёк, обновление (список или полный сбор) запускается в фоне, текущий ответ идёт из кэша, следующий — уже из нового файла. Параллельно двух обновлений не бывает (lock). Причина (2026-10-13): при медленной сети до OpenRouter (`/models` отвечал 16–30 с) ожидание обновления перед ответом делало бота «задумчивым».
- **Фоновый таймер** раз в минуту проверяет сроки, так что данные свежие и без пользователей (и `/new` видит изменения вовремя).
- Ошибка сети → предупреждение в лог, бот работает на последнем снапшоте; если данным > 12 ч, в ответах появляется «данные от …».
- Запись снапшота атомарная (temp + `os.replace`).
- В карточках — обратный отсчёт до `expiration_date`: «бесплатно до 2026-10-31 (через 18 дн.)», за 7 дней — «скоро исчезнет»; `/about` показывает, когда обновлён список, и таймеры.
- GitHub Action (`collect.yml`, раз в 3 ч) остаётся для публичного `data/models.json`; бот с `LOOSECHANGE_DATA_URL` перечитывает его раз в 10 мин.

## Почему так
- Бот не может изменить локальный конфиг пользователя → всегда отдаёт (а) YAML/JSON-сниппет, (б) однострочник `uvx loosechange add …`.
- Нет БД: данные = один JSON в git, история = git log. Дёшево, прозрачно для open source.
- Нет вебхуков/доменов: запускается на любом VPS/Raspberry/Docker.

## Структура репо
```
loosechange/
├─ src/loosechange/
│  ├─ core/                 # данные: без Telegram и без чужих конфигов
│  │  ├─ schema.py          # pydantic: Snapshot, Model, Benchmarks, History
│  │  ├─ collect.py         # OpenRouter → data/models.json (+ history)
│  │  ├─ refresh.py         # обновление по таймерам истечения (список / uptime)
│  │  ├─ profiles.py        # профили задач: веса и требования
│  │  └─ rank.py            # чистое ранжирование
│  ├─ bot/                  # Telegram (aiogram 3, long-polling)
│  │  ├─ main.py            # запуск, .env, логирование, фоновые задачи
│  │  ├─ handlers.py        # команды, коллбэки, антифлуд
│  │  ├─ dialog.py          # кнопки, callback-data, правила свободного текста
│  │  ├─ render.py          # HTML-карточки, пагинация
│  │  ├─ i18n.py            # строки RU/EN
│  │  └─ store.py           # снапшот для бота (файл или URL) + таймеры
│  ├─ integrations/         # куда добавить модель
│  │  ├─ base.py            # Snippet, команда CLI
│  │  ├─ hermes.py          # ~/.hermes/config.yaml (+ .env по --key-file)
│  │  └─ vibeforge.py       # только инструкция
│  └─ cli.py                # loosechange list / show / add / collect
├─ tests/                   # зеркалит src: core/, bot/, integrations/, test_cli.py
│  └─ fixtures/             # реальные срезы OpenRouter API
├─ data/                    # снапшот models.json + history/ (коммитит Action)
├─ docs/                    # решения: ARCHITECTURE, RANKING, DIALOG, INTEGRATIONS, SECURITY, ROADMAP
│  ├─ guides/               # инструкции для пользователей (VibeForge)
│  ├─ reports/              # генерируемые отчёты (самопроверка бота)
│  └─ agent/                # промт автономной сборки
├─ scripts/                 # служебные скрипты (bot_selfcheck.py)
├─ .github/workflows/       # ci.yml, collect.yml
└─ Dockerfile, pyproject.toml, uv.lock
```
Перестройка 2026-10-13: ядро данных вынесено в `core/`, `models.py` → `core/schema.py` (чтобы не путать pydantic-модели с LLM-моделями), тесты разложены по пакетам, документы — по назначению.
Стек: Python 3.12, httpx, pydantic v2, aiogram 3, typer, pytest, ruff, uv.

## Mini App / web — когда
Только если появится потребность в интерактивной таблице с фильтрами. Тогда `site/` — статика (Vite/Vanilla) поверх `models.json`, открываемая и как сайт, и как Telegram Mini App (кнопка меню бота). Бэкенд не нужен.

## Деплой (этап 6)
- **Docker**: `python:3.12-slim`, `uv sync --locked --no-dev --extra bot` (версии из `uv.lock`), непривилегированный пользователь, без открытых портов. По умолчанию бот сам обновляет вложенный снапшот по таймерам (список — 15 мин, uptime — 60 мин); с `LOOSECHANGE_DATA_URL` читает JSON из репозитория.
- **GitHub Actions**: `collect.yml` (cron `17 */3 * * *` + ручной запуск, `contents: write`, коммит только при изменении `data/`; из-за `generated_at`/uptime это почти каждый запуск — история = `git log data/`), `ci.yml` (ruff, ruff format --check, pytest).
- Зависимость `aiogram` вынесена в extra `bot`, чтобы CLI (`uvx loosechange`) ставился легче.
