# Интеграции

Общий принцип: **dry-run по умолчанию**, перед записью — бэкап `config.yaml.bak-<ts>`, ключ в конфиг не пишем, только имя env-переменной.

## Hermes (`~/.hermes/config.yaml`)
Что известно из реального конфига: блок `providers:` — именованные провайдеры с `base_url`, `model`, `models:`; в `model:` — `default`, `provider`, `aliases`, `key_env`; в `fusion`/reference_models используется `provider: openrouter`.
Целевая запись (проверить на живом Hermes — `hermes --help`, `hermes config`, и сменить способ, если есть штатная команда добавления):
```yaml
providers:
  openrouter:
    name: OpenRouter
    base_url: https://openrouter.ai/api/v1
    key_env: OPENROUTER_API_KEY
    models:
      nvidia/nemotron-3-ultra-550b-a55b:free: {}
model:
  aliases:
    free-agent: nvidia/nemotron-3-ultra-550b-a55b:free
```
Алгоритм `apply`: прочитать YAML (ruamel.yaml — сохраняет комментарии!) → merge без перезаписи существующих ключей → алиас по профилю → бэкап → запись → `hermes` smoke-проверка, если команда есть.

## VibeForge (macOS-приложение `/Applications/VibeForge.app`)
Конфиг-формат **неизвестен** — задача первого этапа reverse-engineering: изучить `~/Library/Application Support/com.vibeforge.app/data/` (там `vibeforge.db` — SQLite, `skills/`, `hooks-disabled`), `~/.vibeforge/`, ресурсы .app, UI настроек провайдеров. Не трогать `license-key` и `backend-token`. Если провайдеры хранятся в SQLite — писать только через транзакцию с бэкапом БД и только при закрытом приложении; иначе fallback — пошаговая инструкция со скриншотами/полями UI (`docs/vibeforge-manual.md`). Результат исследования фиксируется в этом файле.

## Универсальный fallback
Для любого OpenAI-совместимого клиента: `base_url=https://openrouter.ai/api/v1`, `model=<id>`, `api_key=$OPENROUTER_API_KEY`.

## Нюансы OpenRouter free
Лимиты на `:free` ограничены (требуют перепроверки по актуальной документации OR: запросы/мин и в сутки, различие с пополненным балансом); без ключа вызовы невозможны — бот напоминает получить ключ на openrouter.ai/keys.
