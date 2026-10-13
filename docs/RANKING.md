# Ранжирование

## Источники (по приоритету)
1. **OpenRouter `benchmarks.artificial_analysis`**: `intelligence_index`, `coding_index`, `agentic_index` (поля могут быть `null`).
2. `benchmarks.design_arena` (для задач «дизайн/вёрстка»), если непустой.
3. Опционально enrichers (v2, за флагом): LMArena, Artificial Analysis API напрямую, Aider leaderboard. Каждый — отдельный модуль, падение не ломает сбор.
4. Нет бенчмарков → модель помечается `unrated`, идёт в конец списка с пометкой «без бенчмарков» (никогда не выдумываем оценку).

## Фильтр «бесплатных»
`pricing.prompt == "0" and pricing.completion == "0"`, исключая `lyria`/image/audio-only по `architecture.output_modalities` (для текстовых профилей нужен `text`). Отдельно помечаем `:free`-варианты (у них жёсткие rate limits) и платные модели с нулевой ценой (`ling-3.1-flash`).

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
