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
