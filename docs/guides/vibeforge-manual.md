# VibeForge: как подключить бесплатную модель OpenRouter

Проверено на VibeForge **2.0.16** (2026-10-14). Автоматической записи нет — настройка делается в интерфейсе (почему — раздел VibeForge в [INTEGRATIONS.md](../INTEGRATIONS.md)).

## 1. Выберите модель
- В боте: `/pick` → «Агент с инструментами» → «VibeForge» → кнопка «🔧 #N → VibeForge» → «📋 Скопировать id модели»; или
- в терминале: `uvx loosechange list --profile agent`.

Id копируйте целиком, с суффиксом `:free` — без него OpenRouter может направить запрос в **платный** вариант.

> ⚠️ На движке «через API» VibeForge **не** считается агентным харнессом для OpenRouter: модели, которые OpenRouter отдаёт только харнессам, отвечают `403 … only available on agentic harnesses` (проверено на `thinkingmachines/inkling-small:free`). Для VibeForge берите модели без этого ограничения — например, `nvidia/nemotron-3-super-120b-a12b:free`, `google/gemma-4-31b-it:free`. Те же inkling-модели работают в Hermes и DeepSeek Harness.

## 2a. Одной командой (VibeForge закрыт)
Закройте VibeForge (⌘Q), затем:
```bash
uvx loosechange add nvidia/nemotron-3-super-120b-a12b:free --to vibeforge --key-file ~/or-key.txt --apply
```
Модель добавится в «Свои модели» OpenRouter (и станет моделью по умолчанию, если её не было; иначе — `--make-default`), ключ — в настройки (если ключа ещё нет). Перед записью делается бэкап базы. Без `--apply` — только показ изменений. Модели 🔒 «только для харнессов» команда не добавит (в VibeForge они дают 403).

## 2b. Вручную: Настройки → Провайдеры → OpenRouter
| Поле | Что вписать |
|---|---|
| API-ключ (`OPENROUTER_API_KEY`) | ключ с https://openrouter.ai/keys (VibeForge хранит его в своей базе открытым текстом) |
| Base URL | пусто (= `https://openrouter.ai/api/v1`) |
| Модель по умолчанию | id из шага 1 |
| Свои модели | список id через запятую → «Добавить» — появятся в выборе модели новой сессии |

Блоки «Свой шлюз или локальный сервер» (LM Studio, Ollama, LiteLLM…) и «Сеть» (прокси только для VibeForge) для OpenRouter не нужны; прокси указывайте, только если OpenRouter недоступен без VPN, и только реально работающий адрес.

Нажмите **«Сохранить провайдеры»**.

## 3. Сессия
1. «Создать» → «Новая сессия … через **API**» (меню движка: Claude Code / Grok / Codex / Kimi / Antigravity / API).
2. Кнопка **🔑** в строке инструментов → **OpenRouter**. Обязательно: иначе провайдер останется Anthropic и сессия упадёт с «Could not resolve authentication method».
3. Модель — из списка или вписать id → Enter (по умолчанию берётся «Модель по умолчанию»).
4. Задача → «Поехали».

## 4. Ошибки
| Сообщение | Причина |
|---|---|
| `Could not resolve authentication method. Expected one of apiKey, authToken…` | провайдер сессии — Anthropic без ключа: выберите OpenRouter кнопкой 🔑 |
| `OpenRouter returned HTTP 403 … only available on agentic harnesses` | модель только для харнессов — возьмите другую (см. шаг 1) |
| `429 … temporarily rate-limited upstream` | free-модель перегружена у провайдера — повторите позже или смените модель |
| «Вход в модель не выполнен» внизу окна | относится к CLI-движкам, для «через API» не важно |
