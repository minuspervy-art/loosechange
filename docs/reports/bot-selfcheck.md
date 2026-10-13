# Самопроверка бота

Сгенерировано `scripts/bot_selfcheck.py` 2026-10-13 11:57 UTC на `data/models.json`: реальные handlers и диспетчер aiogram, Telegram API подменён записывающей сессией. Это не заменяет ручной прогон в Telegram.

**user:** `/start`
**bot (send):**
```
👋 loosechange — бесплатные LLM с OpenRouter, отсортированные по бенчмаркам и подобранные под вашу задачу.

/pick — подобрать модель (2–3 вопроса кнопками)
/top — общий топ без вопросов
/model <id или номер> — карточка модели
/add — как добавить выбранную модель в Hermes / VibeForge
/new — что появилось и исчезло за 7 дней
/lang — English
/about — о проекте
```
кнопки: [🎯 Подобрать] | [🏆 Топ] | [🆕 Что нового]

**user:** `/top`
**bot (send):**
```
Топ: 💬 Чат / общие вопросы · приоритет: 🏆 Максимум качества

1. inclusionAI: Ling 3.1 Flash — ⭐ 100
inclusionai/ling-3.1-flash
🧠 41.1 · 💻 — · 🤖 — · 📏 256k · 🛠 · 💭

2. Thinking Machines: Inkling Small (free) — ⭐ 62.5
thinkingmachines/inkling-small:free
🧠 25.7 · 💻 52.9 · 🤖 23.5 · 📏 1M · 🛠 · 💭

3. Thinking Machines: Inkling (free) — ⭐ 60.8
thinkingmachines/inkling:free
🧠 25 · 💻 52.1 · 🤖 22.5 · 🎨 1167 · 📏 1M · 🛠 · 💭

4. NVIDIA: Nemotron 3 Ultra (free) — ⭐ 55.7
nvidia/nemotron-3-ultra-550b-a55b:free
🧠 22.9 · 💻 49.3 · 🤖 20.1 · 🎨 1128 · 📏 1M · 🛠 · 💭

5. Google: Gemma 4 26B A4B  (free) — ⭐ 40.6
google/gemma-4-26b-a4b-it:free
🧠 16.7 · 💻 39.3 · 🤖 2.9 · 📏 256k · 🛠 · 💭

Стр. 1/4
```
кнопки: [🔧 #1 → Hermes] | [🔧 #1 → VibeForge] / [🔧 #2 → Hermes] | [🔧 #2 → VibeForge] / [🔧 #3 → Hermes] | [🔧 #3 → VibeForge] / [🔧 #4 → Hermes] | [🔧 #4 → VibeForge] / [🔧 #5 → Hermes] | [🔧 #5 → VibeForge] / [Показать все (17)] / [🏠 Меню] | [🔄 Обновить]

**user:** `/pick`
**bot (send):**
```
1/3 · Для чего модель?
```
кнопки: [🤖 Агент с инструментами] | [💻 Код] / [💬 Чат / общие вопросы] | [🧮 Рассуждения / математика] / [📚 Длинные документы] | [⚡ Быстро и дёшево] / [🎨 Дизайн / вёрстка] | [🤷 Не знаю]

**user:** нажимает кнопку `p:purpose:agent`
**bot (edit):**
```
2/3 · Куда будете подключать?
```
кнопки: [Hermes] | [VibeForge] | [Другое]

**user:** нажимает кнопку `p:target:hermes`
**bot (edit):**
```
3/3 · Что важнее?
```
кнопки: [🏆 Максимум качества] / [🛡 Стабильность (uptime)] / [📏 Большой контекст]

**user:** нажимает кнопку `p:priority:quality`
**bot (edit):**
```
Топ: 🤖 Агент с инструментами · приоритет: 🏆 Максимум качества

1. Thinking Machines: Inkling Small (free) — ⭐ 92.5
thinkingmachines/inkling-small:free
🧠 25.7 · 💻 52.9 · 🤖 23.5 · 📏 1M · 🛠 · 💭

2. Thinking Machines: Inkling (free) — ⭐ 89.6
thinkingmachines/inkling:free
🧠 25 · 💻 52.1 · 🤖 22.5 · 🎨 1167 · 📏 1M · 🛠 · 💭

3. NVIDIA: Nemotron 3 Ultra (free) — ⭐ 81.9
nvidia/nemotron-3-ultra-550b-a55b:free
🧠 22.9 · 💻 49.3 · 🤖 20.1 · 🎨 1128 · 📏 1M · 🛠 · 💭

4. Google: Gemma 4 31B (free) — ⭐ 40.7
google/gemma-4-31b-it:free
🧠 14.7 · 💻 43.4 · 🤖 4.2 · 📏 256k · 🛠 · 💭

5. Google: Gemma 4 26B A4B  (free) — ⭐ 36.6
google/gemma-4-26b-a4b-it:free
🧠 16.7 · 💻 39.3 · 🤖 2.9 · 📏 256k · 🛠 · 💭

Стр. 1/3
```
кнопки: [🔧 #1 → Hermes] / [🔧 #2 → Hermes] / [🔧 #3 → Hermes] / [🔧 #4 → Hermes] / [🔧 #5 → Hermes] / [Показать все (15)] / [🏠 Меню] | [🔄 Обновить]

**user:** нажимает «🔧 #1 → Hermes»
**bot (send):**
```
Hermes · thinkingmachines/inkling-small:free
model_aliases:
  free-agent:
    model: "thinkingmachines/inkling-small:free"
    provider: openrouter
    base_url: https://openrouter.ai/api/v1

Или локально одной командой:
uvx loosechange add thinkingmachines/inkling-small:free --to hermes --profile agent --apply
• Команда делает бэкап config.yaml; без --apply — только покажет изменения.
• Ключ: OPENROUTER_API_KEY в ~/.hermes/.env. Ещё нет? Допишите к команде --key-file <файл с ключом> — ключ запишется локально, в бот не отправляется.
• Запуск: hermes -m free-agent
• Free-модели OpenRouter имеют лимиты запросов в минуту и в сутки.
• Нужен ключ OpenRouter: https://openrouter.ai/keys — храните его только у себя.
```
кнопки: [📋 Скопировать команду] / [🏠 Меню]

**user:** `/model thinkingmachines/inkling:free`
**bot (send):**
```
Thinking Machines: Inkling (free)
thinkingmachines/inkling:free
🧠 25 · 💻 52.1 · 🤖 22.5 · 🎨 1167 · 📏 1M · 🛠 · 💭
Inkling is an open-weight multimodal mixture-of-experts model from Thinking Machines Lab, with 41B active parameters out of 975B total. It is designed for general-purpose reasoning, coding, agentic and tool-use systems,...
openrouter.ai/thinkingmachines/inkling:free
```
кнопки: [🔧 Hermes] | [🔧 VibeForge] | [🔧 Другое] / [🏠 Меню]

**user:** `/new`
**bot (send):**
```
За 7 дней
Изменений в списке бесплатных моделей не было.
```
кнопки: [🎯 Подобрать] | [🏆 Топ] | [🆕 Что нового]

