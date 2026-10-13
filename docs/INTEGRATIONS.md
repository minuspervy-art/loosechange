# Интеграции

Общий принцип: **dry-run по умолчанию**, перед записью — бэкап `config.yaml.bak-<ts>`, ключ в конфиг не пишем, только имя env-переменной.

## Hermes (`~/.hermes/config.yaml`) — реализовано (этап 4)
Исследовано 2026-10-13 на Hermes Agent v0.19.1 (`hermes --help`, `hermes config --help`, исходники `hermes_cli/model_switch.py`, `runtime_provider.py`, `oneshot.py`; конфиг читался только на копии).

**Отклонение от первоначального плана и почему:**
- Блок `providers: openrouter:` **не пишем**: `openrouter` — встроенный провайдер Hermes (ключ `OPENROUTER_API_KEY`), а именованная запись `providers.<имя>`, совпадающая с каноническим встроенным провайдером, им затеняется (`_get_named_custom_provider` → «shadowing a canonical provider still resolves to the built-in»).
- `model.aliases.free-agent: nvidia/...:free` **ломается**: строковые алиасы парсятся как `<провайдер>/<модель>` → получился бы провайдер `nvidia`.
- Штатной команды «добавить модель» нет: `hermes model` / `hermes fallback add` — интерактивные пикеры; `hermes config set` перезаписывает файл PyYAML'ом целиком.

**Что пишем** — словарный алиас (читается раньше строковых, см. `_load_direct_aliases`):
```yaml
model_aliases:
  free-agent:            # free-<профиль>, меняется --alias
    model: "nvidia/nemotron-3-ultra-550b-a55b:free"
    provider: openrouter
    base_url: https://openrouter.ai/api/v1
```
Опционально `--fallback` — добавить в `fallback_providers: [{provider: openrouter, model: …}]` (Hermes переключится на free-модель при rate-limit/overload основной).
Использование: `hermes -m free-agent` (oneshot/CLI резолвят `model_aliases` до каталога). Ключ: `OPENROUTER_API_KEY` в `~/.hermes/.env`. Проверено на копии: резолвер Hermes даёт `provider=openrouter, base_url=https://openrouter.ai/api/v1, api_mode=chat_completions`.

**CLI:**
```
loosechange add <id> --to hermes [--profile agent] [--alias NAME] [--fallback] [--config PATH] [--force]   # dry-run: печатает unified diff
loosechange add <id> --to hermes --apply                                                              # бэкап config.yaml.bak-<YYYYmmdd-HHMMSS> + атомарная запись
```
**Алгоритм `apply`** (`integrations/hermes.py`): прочитать YAML (ruamel.yaml, safe-загрузка) → проверить конфликты (алиас уже указывает на другую модель → ошибка, `--force` заменяет только этот алиас; flow-стиль `{…}` с содержимым → отказ, правьте руками) → **точечная текстовая вставка** строк в конец блока `model_aliases`/`fallback_providers` (с отступами, как в файле) или в конец файла → повторный парс результата и сравнение с ожидаемым (исходные данные + ровно наши изменения), иначе отказ → бэкап → запись через temp-файл + `os.replace` с сохранением прав → smoke: `HERMES_HOME=<каталог> hermes config get model_aliases.<alias>.model`.
Почему не round-trip dump ruamel: Hermes сохраняет конфиг PyYAML'ом со сворачиванием длинных строк на 80 колонках, и любой повторный dump (ruamel тоже) переворачивает десятки несвязанных строк (`agent.personalities` и т. п.). Текстовая вставка даёт диф только из наших строк; ruamel используется для разбора и верификации.
Повторный запуск идемпотентен («nothing to change»).

**Ключ OpenRouter из файла (`--key-file`)** — ключ пользователя остаётся на его машине:
```
loosechange add <id> --to hermes --key-file ~/or-key.txt [--replace-key] --apply
```
- Файл любой текстовый (`.txt`, `.env`, даже `.rtf`): ищется ровно один ключ по формату `sk-or-…`; ноль или несколько разных — ошибка.
- Пишется в `<каталог config.yaml>/.env` (для Hermes это `~/.hermes/.env`, путь подтверждён `hermes config env-path`) строкой `OPENROUTER_API_KEY=…`: заменяется первая активная строка с этим именем (закомментированные шаблоны не трогаются), иначе добавляется в конец. Остальные строки файла не меняются.
- Если там уже **другой** ключ — отказ без `--replace-key`. Тот же ключ — «keep», ничего не пишется.
- Dry-run по умолчанию; при `--apply` — бэкап `.env.bak-<время>` (права сохраняются), атомарная запись; новый `.env` создаётся с правами `600`.
- Ключ **нигде не печатается**: в выводе и ошибках только маска `sk-or-v1-…abcd`.
- Без ключа после записи CLI подсказывает `--key-file`.

## VibeForge (macOS-приложение `/Applications/VibeForge.app`) — исследовано (этап 5)
Исследование 2026-10-13, VibeForge 2.0.15, **только чтение**: БД копировалась в scratch и читалась копия; `license-key` и `backend-token` не открывались (значения `app_settings` с key/token в имени не выводились).

**Что нашли**
- Приложение — Tauri-оболочка (`Contents/MacOS/app`) + локальный Node-бэкенд `Contents/Resources/resources/backend/` (`index.cjs` грузит `app.jsc` — V8-байткод через bytenode; `server-bundle.cjs` обфусцирован). Это коммерческий закрытый билд; глубокий реверс не делали — только поиск видимых строк.
- Данные: `~/Library/Application Support/com.vibeforge.app/data/`: `vibeforge.db` (SQLite, drizzle-миграции в ресурсах приложения), `backend-port`, `backend-token`, `cli-update.json`, `guards/worktree-guard.mjs`, `hooks-disabled/`, `skills/`, `uploads/`, `worktrees/`, `workspace-ports.json`; `~/.vibeforge/license-key`.
- Таблицы БД: `sessions`, `agents`, `tasks`, `queue_items`, `logs`, `app_settings`, `installed_skills`, `skill_usages`, `file_changes`, `files`, `agent_errors`, `autopilot_runs`, `session_turns`, `tester_credentials`, `__drizzle_migrations`.
- **Провайдер и модель — поля каждой сессии**, а не глобальный конфиг: `sessions.provider` (default `'anthropic'`), `provider_planner/worker/resolver`, `model_planner/worker/resolver`, `engine` (`claude-code` по умолчанию; встречаются `codex-cli`, `kimi-cli`, `antigravity-cli`, `gemini-cli`), `effort_*`. `agents.model` — модель конкретного агента.
- `app_settings` (key/value) содержит только `license.*` и `mcp.enabled` — **настроек провайдеров там нет**.
- Список провайдеров зашит в бэкенд: строки `anthropic`, `openai`, `openrouter`, `local` рядом с полями `apiKeyEnv`, `defaultBaseUrl`, `defaultModel`, `baseUrlEnv`. Видимые имена переменных: `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `OPENAI_API_KEY`, `KIMI_API_KEY`, `MOONSHOT_API_KEY`; строки `OPENROUTER_API_KEY` в бинаре нет (вероятно, собирается динамически или ключ вводится в UI) — **не подтверждено**.

**Вывод: безопасная автозапись невозможна.**
1. Нет файла/таблицы с пользовательскими провайдерами — писать некуда, кроме строк `sessions`, а это рабочее состояние уже существующих сессий пользователя.
2. Бэкенд держит БД открытой (better-sqlite3); запись из-под работающего приложения рискует гонками, а схема меняется миграциями (30+ штук) без публичного контракта.
3. HTTP-API бэкенда требует `backend-token`, который трогать запрещено.

Поэтому адаптер `integrations/vibeforge.py` — **render-only**: `loosechange add <id> --to vibeforge` печатает пошаговую инструкцию, бот отдаёт «Provider: OpenRouter / Model: <id>». Инструкция: [vibeforge-manual.md](vibeforge-manual.md). Пересмотреть, если VibeForge опубликует конфиг-файл или CLI для провайдеров.

## Универсальный fallback
Для любого OpenAI-совместимого клиента: `base_url=https://openrouter.ai/api/v1`, `model=<id>`, `api_key=$OPENROUTER_API_KEY`.

## Нюансы OpenRouter free
Лимиты на `:free` ограничены (требуют перепроверки по актуальной документации OR: запросы/мин и в сутки, различие с пополненным балансом); без ключа вызовы невозможны — бот напоминает получить ключ на openrouter.ai/keys.
