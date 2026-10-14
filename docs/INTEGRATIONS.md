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

**Обновление 2.0.16 (2026-10-14).** Появилась страница «Настройки → Провайдеры» (Anthropic, OpenAI, **OpenRouter**, «Свой шлюз или локальный сервер», «Сеть/прокси»). Значения хранятся в `vibeforge.db`, таблица `app_settings`, под именами env-переменных: `OPENROUTER_API_KEY` (**ключ открытым текстом**, файл БД `0600`), `VIBEFORGE_OPENROUTER_MODEL` (модель по умолчанию), `VIBEFORGE_OPENROUTER_MODELS` (свои модели, строка через запятую), `VIBEFORGE_OPENROUTER_BASE_URL`, прокси — `VIBEFORGE_PROXY`. Провайдер сессии выбирается кнопкой 🔑 в строке новой сессии при движке «через API»; без этого сессия остаётся `provider=anthropic` и падает с ошибкой SDK Anthropic «Could not resolve authentication method» (проверено). Автоматизировать UI агентом нельзя (веб-интерфейс без accessibility).

**Адаптер (реализован 2026-10-14, `integrations/vibeforge.py`):**
```
loosechange add <id> --to vibeforge [--make-default] [--key-file ~/or.txt [--replace-key]] [--config <db>] [--apply]
```
- Пишет **только** строки `app_settings`: `VIBEFORGE_OPENROUTER_MODELS` (добавляет id, порядок и остальные модели сохраняются), `VIBEFORGE_OPENROUTER_MODEL` (только если пусто или `--make-default`), `OPENROUTER_API_KEY` (только с `--key-file`; другой ключ — отказ без `--replace-key`). `license.*`, сессии и прочие таблицы не трогаются.
- **Только при закрытом VibeForge** (`pgrep -f '^/Applications/VibeForge\.app/Contents/'` — и окно `app`, и бэкенд `node index.cjs`; шаблон привязан к началу команды: без `^` он ловил любой процесс, в аргументах которого упомянут путь): иначе отказ «quit it (⌘Q)». Приложение держит настройки в памяти и перезаписало бы нашу правку.
- Перед записью — целостный бэкап через SQLite backup API (`vibeforge.db.bak-<время>`, `600`, включает WAL), затем одна транзакция `BEGIN IMMEDIATE`, чтение назад для проверки.
- Модели 🔒 `harness_only` (из `loosechange probe`) — отказ без `--force`: на движке API они дают 403 (проверено).
- Проверено на целостной копии реальной БД (`sqlite3 .backup`, только чтение живой БД): dry-run, apply, повтор, ключ «already set»; реальная БД не изменилась (сверка по `updated_at`).
- Бот: сниппет VibeForge — кнопка «📋 Скопировать команду» (`… --to vibeforge --apply`) с предупреждением закрыть VibeForge.

**Без набора: `loosechange sync --to vibeforge` + иконка + launchd (2026-10-14).**
- `sync` сам выбирает модели (`core/select.py`): топ-N (по умолчанию 3) профиля `agent`, без 🔒 `harness_only`, без роутера, без моделей с uptime < 90%, сначала проверенные `open`; добавляет недостающие в `VIBEFORGE_OPENROUTER_MODELS`; модель по умолчанию меняет только если её нет, она исчезла из бесплатных или 🔒. Снапшот старше `--max-age` (60 мин) сначала обновляется `quick_collect` (вердикты доступа сохраняются).
- `--restart`: если VibeForge открыт — проверка «занят» по его БД (только чтение: агенты в статусе, отличном от `idle/failed/completed/stopped/paused/…`, или `running` в `queue_items`/`autopilot_runs` → отказ, код 3), затем `osascript … to quit` (как ⌘Q), ожидание выхода обоих процессов, запись, `open -b com.vibeforge.app`. `--if-closed`: открытый VibeForge — тихий пропуск.
- Проверка «запущен»: `pgrep -f '^/Applications/VibeForge\.app/Contents/'`. Без `^` шаблон ловил посторонние процессы, в аргументах которых встречался путь (найдено на живом прогоне).
- `scripts/macos/install.sh` ставит иконку (AppleScript-апплет, режим `--restart`) и LaunchAgent `com.loosechange.vibeforge-sync` (каждые 3 ч, `--if-closed`). **Факт macOS:** фоновым заданиям launchd запрещён доступ к `~/Documents` (TCC → `Operation not permitted`), поэтому установщик выносит всё за пределы проекта: CLI — `uv tool install` (`~/.local/bin/loosechange`), скрипт и данные (`models.json`, `access.json`) — `~/Library/Application Support/loosechange/`. Полный доступ к диску для bash не выдаём.
- **Чистка (с 2026-10-14):** `sync --to vibeforge` удаляет из «Своих моделей» только `:free`-модели, которые стали 🔒, исчезли из бесплатных или перегружены (429 < 12 ч), — с причиной в выводе; платные и прочие id не трогает. Отключить: `--no-remove`. Модель по умолчанию заменяется и если она перегружена. Перед выбором `sync` читает журнал ошибок VibeForge за 24 ч.
- Проверено вживую: задание launchd добавило `nemotron-3.5-lightning:free` в реальный VibeForge (с бэкапом БД, модель по умолчанию не тронута); иконка → «модели VibeForge актуальны».

**Вывод для 2.0.15: безопасная автозапись невозможна.**
1. Нет файла/таблицы с пользовательскими провайдерами — писать некуда, кроме строк `sessions`, а это рабочее состояние уже существующих сессий пользователя.
2. Бэкенд держит БД открытой (better-sqlite3); запись из-под работающего приложения рискует гонками, а схема меняется миграциями (30+ штук) без публичного контракта.
3. HTTP-API бэкенда требует `backend-token`, который трогать запрещено.

Поэтому адаптер `integrations/vibeforge.py` — **render-only**: `loosechange add <id> --to vibeforge` печатает пошаговую инструкцию, бот отдаёт «Provider: OpenRouter / Model: <id>». Инструкция: [guides/vibeforge-manual.md](guides/vibeforge-manual.md). Пересмотреть, если VibeForge опубликует конфиг-файл или CLI для провайдеров.

## Установка в один клик (`loosechange://`, 2026-10-14)
`deeplink.py` (строгий разбор/сборка ссылки), `oneclick.py` (`check` → ASK / ASK_RESTART / DONE / ERROR, `apply` — через те же адаптеры, с бэкапом; явный выбор модели = Hermes `--force`, DSH `--force`, VibeForge `--make-default`), CLI `loosechange open-url --mode check|apply|apply-restart <url>` (служебная).
Обработчик macOS — AppleScript-апплет `~/Applications/loosechange.app` (`scripts/macos/LinkHandler.applescript`): `CFBundleURLTypes` со схемой `loosechange`, `CFBundleIdentifier dev.loosechange.handler`, ad-hoc подпись, `lsregister`. Окна подтверждения показывает сам апплет (без запроса прав Automation). Раннер `loosechange-open.sh` копируется в `~/Library/Application Support/loosechange/` (как и sync — из-за TCC). Лог: `~/Library/Logs/loosechange/links.log`.
Промежуточная страница `site/add.html` публикуется `.github/workflows/pages.yml` на GitHub Pages; бот показывает кнопку, только если `LOOSECHANGE_LINK_BASE` начинается с `https://`.
Проверено: `open 'loosechange://add?model=nvidia/nemotron-3-super-120b-a12b:free&to=vibeforge&profile=agent'` → macOS отдал ссылку апплету → «Уже установлена в VibeForge». Страница на локальном сервере: корректная ссылка → кнопка `loosechange://…`, подделанная (`;rm -rf`, лишний `key`) → «Ссылка повреждена». Нюанс установщика: `osacompile` не пишет `CFBundleIdentifier` → поле добавляется, а не изменяется.

## Универсальный fallback
Для любого OpenAI-совместимого клиента: `base_url=https://openrouter.ai/api/v1`, `model=<id>`, `api_key=$OPENROUTER_API_KEY`.

## Нюансы OpenRouter free
**Free-модели «только для агентных харнессов»** (факт 2026-10-13): `thinkingmachines/inkling-small:free` на прямой запрос с ключом отвечает `403 … is only available on agentic harnesses. Try plugging it into a coding agent or productivity app listed on https://openrouter.ai/apps`. Через Hermes (он шлёт `HTTP-Referer: https://hermes-agent.nousresearch.com`, `X-Title: Hermes Agent`) та же модель с тем же ключом отвечает нормально — проверено `hermes -z … -m thinkingmachines/inkling-small:free --provider openrouter` на копии конфига. В `/models` и `/endpoints` признака такого ограничения **нет** — узнать можно только вызовом, поэтому в данных он не отражён (не выдумываем). Заголовки чужих приложений loosechange не подделывает. В сниппете «Другое» — предупреждение.

Проверка по харнессам (2026-10-13, один и тот же ключ, промпт «Reply with exactly one word: ok»):
| Клиент | `inkling-small:free` | контроль `nemotron-3-super-120b-a12b:free` |
|---|---|---|
| прямой HTTP-запрос (curl/скрипт) | ❌ 403 «only available on agentic harnesses» | ✅ |
| прямой запрос + поле `tools` | ❌ 403 — одно наличие tools ограничение не снимает | — |
| Hermes v0.19.1 (`hermes -z … --provider openrouter`) | ✅ «ok» | — |
| DeepSeek Harness 0.2.0-rc.2 (`dsh headless`) | ✅ «ok» | ✅ «ok» |
| VibeForge 2.0.16, движок **API** + провайдер OpenRouter | ❌ **403** «only available on agentic harnesses» (2026-10-14, ручной тест владельца: сессия `engine=api, provider=openrouter`, модель из «Модели по умолчанию»). Значит, на движке API VibeForge харнессом для OpenRouter **не считается** — брать модели без этого ограничения (например, `nemotron-3-super-120b-a12b:free`). CLI-движки VibeForge (Claude Code, Codex CLI, …) с OpenRouter не проверялись | — |
Как OpenRouter распознаёт харнесс, по коду однозначно не видно: у DeepSeek Harness нет `HTTP-Referer`/`X-Title` в исходниках, но он проходит. Не реверсили дальше намеренно (подбирать признаки для обхода ограничения не будем).

## DeepSeek Harness (`/Applications/DeepSeek Harness.app`, `com.deepseek.dsh`) — исследовано
Electron + CLI `Contents/Resources/runtime/cli/bin/dsh`; конфигурация — стек YAML-слоёв плагинов (Cordis), пользовательские данные — `$DSH_HOME` (профили в `$DSH_HOME/profiles`), данные приложения — `~/Library/Application Support/@deepseek-ai/dsh-desktop`. OpenRouter подключается плагином `@deepseek-ai/dsh-llm-pi-ai` (библиотека pi-ai), модель по умолчанию — слоем `agent-default-model`. Рабочий оверлей (проверен `dsh --profile headless --patch <файл> "…"` в изолированном `DSH_HOME`, ключ только в env процесса, на диск не попал):
```yaml
- id: llm-pi-ai
  config:
    providers:
      openrouter:
        displayName: OpenRouter
        api: openai-completions
        baseURL: https://openrouter.ai/api/v1
        apiKeyEnv: OPENROUTER_API_KEY
        models:
          - id: thinkingmachines/inkling-small:free
- id: agent-default-model
  config:
    provider: openrouter
    model: thinkingmachines/inkling-small:free
- id: session-title-llm   # иначе заголовки сессий идут в deepseek-official и требуют DEEPSEEK_API_KEY
  disabled: true
```
Важно: в патчах `config` **заменяется целиком**, не сливается — перечисляйте все нужные поля.

**Реализовано (2026-10-14), `integrations/deepseek_harness.py`:**
```
loosechange add <id> --to deepseek [--dsh-profile desktop] [--key-file ~/or.txt] [--force] [--apply]
```
- Пишет в пользовательский слой профиля `$DSH_HOME/profiles/<профиль>/cordis.patch.yml` (по умолчанию `~/.dsh/profiles/desktop/` — профиль GUI-приложения; слой hot-reload, перезапуск не нужен). `desktop` нельзя собрать через CLI («managed exclusively by the Electron application»), но он состоит из тех же бандлов, что поставляемый `web` (`dsh-base` + `dsh-web-app`).
- Так как `config` в патче заменяет конфиг плагина целиком, адаптер **сливает** изменения в существующие записи: в `llm-pi-ai.providers.openrouter.models` добавляет модель, другие провайдеры и уже заданные поля (например, свой `apiKeyEnv`) сохраняет; записи с `!!js` не трогает (если сам `config` — выражение, отказ). Другой default-модели — отказ без `--force` (`reasoningEffort` сохраняется).
- Комментарии-заголовок файла сохраняются (ruamel round-trip), `[]` приложения превращается в блочный список. После правки — проверка: все чужие записи совпадают как данные, наша модель и default на месте.
- Бэкап `cordis.patch.yml.bak-<время>`, атомарная запись, права сохраняются (новые файлы — `600`).
- `--key-file` → `OPENROUTER_API_KEY` в `$DSH_HOME/.env` (машинные env-дефолты харнесса), маска в выводе.
- Smoke-проверка: `dsh --profile web --patch <записанный файл> --dump-config` во **временном** `DSH_HOME` → `default model -> openrouter/<id>`.
- Проверено на копии профиля пользователя: dry-run не пишет; apply + повтор («nothing to change»); сквозной вызов `dsh headless` с записанным патчем и ключом **из `.env` копии** (без ключа в окружении) → модель `inkling-small:free` ответила «ok».
**Проверка всего списка (`loosechange probe --key-file …`, 2026-10-14)** — по одному запросу `Reply with exactly one word: ok` на модель, как обычный клиент (без чужих заголовков), ключом владельца, $0:
| Вердикт | Модели |
|---|---|
| ✅ `open` (10) | cohere/north-mini-code, dots-studio/dots-3-note-preview, liquid/lfm-2.5-2.6b, nvidia/nemotron-3-nano-omni-30b-a3b-reasoning, nvidia/nemotron-3-super-120b-a12b, nvidia/nemotron-3-ultra-550b-a55b, nvidia/nemotron-3.5-content-safety, nvidia/nemotron-3.5-lightning, poolside/laguna-s-2.1, poolside/laguna-xs-2.1 (все `:free`) |
| 🔒 `harness_only` (2) | thinkingmachines/inkling-small:free, thinkingmachines/inkling:free |
| неизвестно (2) | google/gemma-4-26b-a4b-it:free, google/gemma-4-31b-it:free — дважды `429` от Google AI Studio; вердикт не ставим |
Результаты — в `data/access.json` (без ключа) и полем `access` в `data/models.json`; переживают обновления по таймерам. `429`/ошибки не стирают прежний вердикт. Роутер `openrouter/free` не проверяется (случайная модель). В боте: 🔒 в карточке, для VibeForge/«Другое» такие модели скрыты с пояснением «Скрыто N…», у них нет кнопок VibeForge/«Другое». Повторять проверку стоит при появлении новых моделей.

**Перегрузка (429) как данные (2026-10-14).** Бесплатные gemma обслуживает Google AI Studio из **общего пула на всех пользователей OpenRouter** (`limit_source: upstream_provider_shared_pool`): когда он выбран, 429 получают все, независимо от ключа. Наблюдённые 429 хранятся в `access.json → congestion` (время, сколько подряд, источник `probe` / `vibeforge-log`), в снапшоте — `congested_at`, если 429 был < 12 ч назад; успешный ответ снимает метку. Источники: `loosechange probe` и **журнал ошибок самого VibeForge** (`logs`, только чтение: «… is temporarily rate-limited upstream» → 429, «… only available on agentic harnesses» → 🔒). Бот показывает «⏳ перегружена: 429 в HH:MM», `sync` такие модели не выбирает.

Free-модели также часто отвечают `429 … temporarily rate-limited upstream` — это перегрузка у провайдера, не проблема ключа; помогает повтор позже или другая модель из списка.

Лимиты на `:free` ограничены (требуют перепроверки по актуальной документации OR: запросы/мин и в сутки, различие с пополненным балансом); без ключа вызовы невозможны — бот напоминает получить ключ на openrouter.ai/keys.
