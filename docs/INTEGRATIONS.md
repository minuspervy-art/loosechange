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

## VibeForge (macOS-приложение `/Applications/VibeForge.app`)
Конфиг-формат **неизвестен** — задача первого этапа reverse-engineering: изучить `~/Library/Application Support/com.vibeforge.app/data/` (там `vibeforge.db` — SQLite, `skills/`, `hooks-disabled`), `~/.vibeforge/`, ресурсы .app, UI настроек провайдеров. Не трогать `license-key` и `backend-token`. Если провайдеры хранятся в SQLite — писать только через транзакцию с бэкапом БД и только при закрытом приложении; иначе fallback — пошаговая инструкция со скриншотами/полями UI (`docs/vibeforge-manual.md`). Результат исследования фиксируется в этом файле.

## Универсальный fallback
Для любого OpenAI-совместимого клиента: `base_url=https://openrouter.ai/api/v1`, `model=<id>`, `api_key=$OPENROUTER_API_KEY`.

## Нюансы OpenRouter free
Лимиты на `:free` ограничены (требуют перепроверки по актуальной документации OR: запросы/мин и в сутки, различие с пополненным балансом); без ключа вызовы невозможны — бот напоминает получить ключ на openrouter.ai/keys.
