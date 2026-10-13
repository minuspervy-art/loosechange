"""VibeForge adapter: render-only.

VibeForge (macOS, v2.0.15 researched) has no user-editable provider config: the
provider and model are columns of each session row in its SQLite DB and the
provider list (anthropic / openai / openrouter / local) is compiled into the app.
Writing session rows of a running app is not safe, so we print instructions.
Details: docs/INTEGRATIONS.md, docs/guides/vibeforge-manual.md.
"""

from __future__ import annotations

from .base import ApplyNotSupported, Snippet

MANUAL_URL = "docs/guides/vibeforge-manual.md"


def render(model_id: str, profile: str) -> Snippet:
    body = f"Provider: OpenRouter\nModel:    {model_id}"
    return Snippet(
        target="vibeforge",
        language="text",
        body=body,
        # no terminal command: there is nothing to apply locally, the id goes into the UI
        copy_text=model_id,
        notes={
            "ru": [
                "Настройки → Провайдеры → OpenRouter: ключ и id модели (в «Свои модели»). "
                "Новая сессия «через API» → 🔑 → OpenRouter → модель.",
                "На движке API VibeForge не считается харнессом: модели «только для "
                "харнессов» (напр. inkling) дадут 403 — берите nemotron/gemma.",
            ],
            "en": [
                "Settings → Providers → OpenRouter: key and model id (in custom models). "
                "New session via API → 🔑 → OpenRouter → model.",
                "On the API engine VibeForge is not an agentic harness: harness-only "
                "models (e.g. inkling) return 403 — use nemotron/gemma.",
            ],
        },
    )


def manual(model_id: str) -> str:
    return "\n".join(
        [
            "VibeForge (2.0.16) is set up in the app — loosechange does not write to it:",
            "  1. Settings → Providers → OpenRouter: API key, and add the model to custom models.",
            "  2. New session «via API» → 🔑 → OpenRouter (otherwise it stays Anthropic).",
            f"  3. Model:    {model_id}",
            "  4. Harness-only models (e.g. thinkingmachines/inkling*) return 403 in VibeForge.",
            f"Full guide: {MANUAL_URL}",
        ]
    )


def apply(model_id: str, profile: str, dry_run: bool = True):
    raise ApplyNotSupported("VibeForge has no user-editable provider config; follow " + MANUAL_URL)
