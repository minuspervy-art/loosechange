"""VibeForge adapter: render-only (no safely writable config, see docs/INTEGRATIONS.md)."""

from __future__ import annotations

from .base import OPENROUTER_KEY_ENV, ApplyNotSupported, Snippet, cli_command

MANUAL_URL = "docs/vibeforge-manual.md"


def render(model_id: str, profile: str) -> Snippet:
    body = f"Provider: OpenRouter\nModel:    {model_id}"
    return Snippet(
        target="vibeforge",
        language="text",
        body=body,
        command=cli_command(model_id, "vibeforge", profile),
        notes={
            "ru": [
                "VibeForge хранит провайдера и модель в настройках сессии — "
                "выберите их в UI (CLI покажет пошаговую инструкцию).",
                f"Ключ OpenRouter — переменная {OPENROUTER_KEY_ENV}.",
            ],
            "en": [
                "VibeForge keeps provider and model per session — pick them in the UI "
                "(the CLI prints step-by-step instructions).",
                f"OpenRouter key: the {OPENROUTER_KEY_ENV} variable.",
            ],
        },
    )


def apply(model_id: str, profile: str, dry_run: bool = True):
    raise ApplyNotSupported("VibeForge has no user-editable provider config; follow " + MANUAL_URL)
