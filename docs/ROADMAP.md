# Roadmap

| # | Этап | Готово, когда |
|---|---|---|
| 0 | Скелет: pyproject, ruff, pytest, CI | `uv run pytest` зелёный в пустом проекте — ✅ |
| 1 | Collector + `models.json` | скрипт даёт ≥15 free-моделей, схема pydantic, фикстура в tests — ✅ 17 моделей |
| 2 | Ranker + профили | тесты на каждый профиль, null-бенчмарки → unrated — ✅ |
| 3 | Бот: /top, /pick, /model | прогон в реальном Telegram с токеном из `.env`; скриншоты в docs/ — ⚠️ бот запущен вживую (long-polling, команды зарегистрированы), диалог проверен самопроверкой [reports/bot-selfcheck.md](reports/bot-selfcheck.md); ручной прогон из Telegram-клиента и скриншоты — за владельцем |
| 4 | Интеграция Hermes | `loosechange add … --to hermes --dry-run` показывает диф; apply проходит на копии конфига — ✅ 2026-10-13 |
| 5 | Интеграция VibeForge | исследование → адаптер или manual-инструкция — ✅ 2.0.15: только инструкция; 2.0.16: адаптер в `app_settings` (только при закрытом приложении, бэкап БД) + [guides/vibeforge-manual.md](guides/vibeforge-manual.md); на движке API VibeForge не харнесс (403 для 🔒-моделей) |
| 5b | Интеграция DeepSeek Harness | адаптер с dry-run/бэкапом, проверка на копии профиля и сквозной вызов `dsh headless` — ✅ 2026-10-14 |
| 6 | GitHub Action + Dockerfile + README quickstart | cron обновляет JSON, `docker run` поднимает бота — ✅ файлы готовы; Docker локально не установлен, шаги образа и workflow эмулированы в чистой копии (uv sync --locked --no-dev --extra bot → бот стартует, collect работает); реальные `docker build` и запуск Action — после публикации |
| 7 (v2) | Статичная страница/Mini App, enrichers (LMArena, Aider), LLM-классификатор задач | по желанию |
