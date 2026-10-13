# Архитектура

## Решение: бот + CLI + статический JSON
```
GitHub Action (cron 3ч)         ┌── bot (aiogram) ── Telegram
  collector ──► data/models.json┤
  (OR API + enrichers)          ├── CLI loosechange (add/list/pick)
                                └── site/ (GitHub Pages, v2)
```
- **Collector** — Python-модуль `loosechange.collect`: тянет OpenRouter `/models`, фильтрует `:free`, нормализует, мерджит бенчмарки, пишет `data/models.json` + `data/history/` (дифф: новые/исчезнувшие модели).
- **Ranker** — чистые функции `rank(models, profile) -> list[Scored]` ([RANKING.md](RANKING.md)). Без сети, полностью тестируемо.
- **Bot** — aiogram 3, long-polling (без вебхука и домена). Читает JSON с диска/из raw GitHub, кеш в памяти. Состояние диалога — in-memory FSM (потеря при рестарте допустима).
- **CLI** — `pipx install loosechange` / `uvx loosechange`. Команды: `list --profile coding`, `add <model-id> --to hermes|vibeforge [--dry-run]`.
- **Integrations** — адаптеры `integrations/hermes.py`, `integrations/vibeforge.py` с общим интерфейсом `render(model) -> Snippet` и `apply(model, dry_run)`.

## Collector и схема `data/models.json` (этап 1, реализовано)
Запуск: `uv run python -m loosechange.collect` (или `loosechange collect`). Схема — pydantic `Snapshot` в `src/loosechange/models.py`, `schema_version: 1`:
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
| `LOOSECHANGE_SELF_COLLECT_HOURS` | если > 0 и URL не задан — бот сам запускает коллектор с этим интервалом (для Docker без GitHub Action) |
| `LOOSECHANGE_CLI` | префикс команды в сниппетах и кнопке «Скопировать команду», по умолчанию `uvx loosechange`; локально удобно `uv run --project <путь к репо> loosechange` |
Токен дополнительно вырезается из любых строк логов (`RedactFilter`), логгер httpx приглушён до WARNING.

## Почему так
- Бот не может изменить локальный конфиг пользователя → всегда отдаёт (а) YAML/JSON-сниппет, (б) однострочник `uvx loosechange add …`.
- Нет БД: данные = один JSON в git, история = git log. Дёшево, прозрачно для open source.
- Нет вебхуков/доменов: запускается на любом VPS/Raspberry/Docker.

## Структура репо
```
loosechange/
├─ src/loosechange/{collect,rank,profiles,models,cli}.py
├─ src/loosechange/bot/{main,handlers,dialog,render}.py
├─ src/loosechange/integrations/{hermes,vibeforge}.py
├─ data/models.json            # снапшот (коммитится Action'ом)
├─ tests/                      # pytest, фикстуры = реальные срезы OR API
├─ .github/workflows/{collect.yml,ci.yml}
├─ Dockerfile, pyproject.toml, docs/
```
Стек: Python 3.12, httpx, pydantic v2, aiogram 3, typer, pytest, ruff, uv.

## Mini App / web — когда
Только если появится потребность в интерактивной таблице с фильтрами. Тогда `site/` — статика (Vite/Vanilla) поверх `models.json`, открываемая и как сайт, и как Telegram Mini App (кнопка меню бота). Бэкенд не нужен.

## Деплой (этап 6)
- **Docker**: `python:3.12-slim`, `uv sync --locked --no-dev --extra bot` (версии из `uv.lock`), непривилегированный пользователь, без открытых портов. По умолчанию бот сам обновляет вложенный снапшот каждые 3 ч; с `LOOSECHANGE_DATA_URL` читает JSON из репозитория.
- **GitHub Actions**: `collect.yml` (cron `17 */3 * * *` + ручной запуск, `contents: write`, коммит только при изменении `data/`; из-за `generated_at`/uptime это почти каждый запуск — история = `git log data/`), `ci.yml` (ruff, ruff format --check, pytest).
- Зависимость `aiogram` вынесена в extra `bot`, чтобы CLI (`uvx loosechange`) ставился легче.
