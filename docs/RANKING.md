# Ранжирование

## Источники (по приоритету)
1. **OpenRouter `benchmarks.artificial_analysis`**: `intelligence_index`, `coding_index`, `agentic_index` (поля могут быть `null`).
2. `benchmarks.design_arena` (для задач «дизайн/вёрстка»), если непустой.
3. Опционально enrichers (v2, за флагом): LMArena, Artificial Analysis API напрямую, Aider leaderboard. Каждый — отдельный модуль, падение не ломает сбор.
4. Нет бенчмарков → модель помечается `unrated`, идёт в конец списка с пометкой «без бенчмарков» (никогда не выдумываем оценку).

## Фильтр «бесплатных»
`pricing.prompt == "0" and pricing.completion == "0"` (сравнение как float), исключая модели, у которых `architecture.output_modalities` не равно ровно `["text"]` — так отсекаются `lyria` (text+audio, генерация музыки) и image/audio-генераторы. Исключённые попадают в `excluded[]` снапшота с причиной. Отдельно помечаем `:free`-варианты (у них жёсткие rate limits) и платные модели с нулевой ценой (`ling-3.1-flash`).

## Профили (ответ на вопрос «для чего?»)
| Профиль | Формула (нормализация 0–100 по max среди кандидатов) | Жёсткие требования |
|---|---|---|
| `agent` (Hermes/VibeForge, tool-calling) | 0.5·agentic + 0.3·coding + 0.2·intelligence | `tools` в supported_parameters, ctx ≥ 128k |
| `coding` | 0.7·coding + 0.3·intelligence | tools желательно |
| `chat` / общие | 1.0·intelligence | — |
| `reasoning` | 0.7·intelligence + 0.3·coding | `reasoning` в supported_parameters |
| `longctx` (документы) | 0.5·intelligence + 0.5·log(ctx) | ctx ≥ 256k |
| `fast_cheap` (классификация, саммари) | 0.4·intelligence + 0.6·скорость* | — |
| `design` | design_arena, fallback coding | — |
*скорость — из endpoints/uptime OR, если доступна; иначе профиль недоступен.

`null`-компонент: вес перераспределяется на имеющиеся, но если нет **основного** индекса профиля — модель в `unrated`.

## Надёжность (штрафы)
Из `/models/{id}/endpoints`: uptime, p50 latency, throughput. Модель с uptime < 90% за последние 30 мин получает метку ⚠️ и −10 к скору. Бесплатные модели часто исчезают (`expiration_date`) — показываем дату и предупреждаем за 7 дней.

## Выдача
Топ-5 по профилю: место, id, скор, 3 индекса, ctx, tools/reasoning-иконки, ссылка. Кнопка «Показать все» (пагинация). Формулы и веса лежат в `profiles.py` и покрыты тестами; PR с изменением весов должен приложить обоснование.

## Реализация (этап 2) — уточнения
Код: `src/loosechange/profiles.py` (веса/требования), `src/loosechange/rank.py` (чистая `rank(models, profile, priority)`), тесты `tests/test_rank.py`.
- **Нормализация** — по max среди кандидатов профиля (моделей, прошедших жёсткие требования), поэтому скор относительный: 100 = лучший из бесплатных сейчас.
- **`design`**: `design_elo` = среднее Elo по категориям арены `models` из `benchmarks.design_arena` (категории `agents` в среднее не входят — у них другая шкала и мало моделей). Модели без арены, но с `coding_index`, ранжируются по coding **после** всех моделей с ареной и получают метку `fallback`: шкалы несопоставимы, смешивать их в один скор нельзя.
- **`longctx`**: компонент `ctx` = min-max по `log(context_length)`, нижняя граница = требование профиля (256k) → 256k даёт 0, максимальный контекст среди кандидатов — 100. Причина: `log(ctx)/log(max)` давал 90–100 для всех и не различал 256k и 1M.
- **`fast_cheap`**: факт 2026-10-13 — публичный `/endpoints` не отдаёт `throughput_last_30m`/`latency_last_30m` (всегда `null`), поэтому профиль сейчас **недоступен** (`available=false, reason=no_speed_data`); бот предлагает профиль `chat`. Как только OR начнёт отдавать throughput — профиль включится сам.
- **`coding` «tools желательно»** → −5 к скору без `tools` (метка `no_tools`).
- **Приоритет (вопрос 3 диалога)**: `quality` — формула как есть; `stability` — `0.8·скор + 0.2·uptime_30m` (нет данных uptime → 0 и метка `no_uptime_data`); `context` — `0.8·скор + 0.2·ctx`. Доля 0.2 — `PRIORITY_BLEND`.
- Штрафы применяются после приоритета; скор обрезается снизу нулём, округляется до 0.1.
- `openrouter/free` (роутер на случайную free-модель) остаётся в списке, но без бенчмарков → всегда `unrated`.
