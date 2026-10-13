"""VibeForge adapter: render-only.

VibeForge (macOS, v2.0.15 researched) has no user-editable provider config: the
provider and model are columns of each session row in its SQLite DB and the
provider list (anthropic / openai / openrouter / local) is compiled into the app.
Writing session rows of a running app is not safe, so we print instructions.
Details: docs/INTEGRATIONS.md, docs/vibeforge-manual.md.
"""

from __future__ import annotations

from .base import ApplyNotSupported, Snippet, cli_command

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
                "VibeForge хранит провайдера и модель в настройках каждой сессии: "
                "в новой сессии выберите провайдера OpenRouter и вставьте id модели.",
                "Ключ OpenRouter задаётся в VibeForge; автозаписи нет — только вручную.",
            ],
            "en": [
                "VibeForge keeps provider and model per session: in a new session pick "
                "the OpenRouter provider and paste the model id.",
                "The OpenRouter key is set inside VibeForge; there is no auto-write.",
            ],
        },
    )


def manual(model_id: str) -> str:
    return "\n".join(
        [
            "VibeForge has no config file loosechange can safely edit — set it in the app:",
            "  1. Open VibeForge and start a new session (or open session settings).",
            "  2. Provider: OpenRouter   (for planner / worker / resolver as you need).",
            f"  3. Model:    {model_id}",
            "  4. Make sure your OpenRouter API key is configured for VibeForge.",
            f"Full guide: {MANUAL_URL}",
        ]
    )


def apply(model_id: str, profile: str, dry_run: bool = True):
    raise ApplyNotSupported("VibeForge has no user-editable provider config; follow " + MANUAL_URL)
