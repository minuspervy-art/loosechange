# Roadmap

| # | Этап | Готово, когда |
|---|---|---|
| 0 | Скелет: pyproject, ruff, pytest, CI | `uv run pytest` зелёный в пустом проекте |
| 1 | Collector + `models.json` | скрипт даёт ≥15 free-моделей, схема pydantic, фикстура в tests |
| 2 | Ranker + профили | тесты на каждый профиль, null-бенчмарки → unrated |
| 3 | Бот: /top, /pick, /model | прогон в реальном Telegram с токеном из `.env`; скриншоты в docs/ |
| 4 | Интеграция Hermes | `loosechange add … --to hermes --dry-run` показывает диф; apply проходит на копии конфига |
| 5 | Интеграция VibeForge | исследование → адаптер или manual-инструкция |
| 6 | GitHub Action + Dockerfile + README quickstart | cron обновляет JSON, `docker run` поднимает бота |
| 7 (v2) | Статичная страница/Mini App, enrichers (LMArena, Aider), LLM-классификатор задач | по желанию |
