"""Hermes Agent adapter (~/.hermes/config.yaml)."""

from __future__ import annotations

from .base import OPENROUTER_BASE_URL, OPENROUTER_KEY_ENV, Snippet, alias_for, cli_command


def alias_entry(model_id: str) -> dict[str, str]:
    return {"model": model_id, "provider": "openrouter", "base_url": OPENROUTER_BASE_URL}


def render(model_id: str, profile: str) -> Snippet:
    alias = alias_for(profile)
    body = (
        "model_aliases:\n"
        f"  {alias}:\n"
        f'    model: "{model_id}"\n'
        "    provider: openrouter\n"
        f"    base_url: {OPENROUTER_BASE_URL}\n"
    )
    return Snippet(
        target="hermes",
        language="yaml",
        body=body,
        command=cli_command(model_id, "hermes", profile),
        notes={
            "ru": [
                f"Ключ: {OPENROUTER_KEY_ENV} в ~/.hermes/.env. Запуск: hermes -m {alias}",
                "Free-модели OpenRouter имеют лимиты запросов в минуту и в сутки.",
            ],
            "en": [
                f"Key: {OPENROUTER_KEY_ENV} in ~/.hermes/.env. Run: hermes -m {alias}",
                "OpenRouter free models are rate-limited per minute and per day.",
            ],
        },
    )
