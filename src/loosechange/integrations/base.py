"""Shared bits of the integration adapters (docs/INTEGRATIONS.md)."""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_KEY_ENV = "OPENROUTER_API_KEY"
# straight from the repo: the bare name `loosechange` on PyPI is not ours (see SECURITY.md)
DEFAULT_CLI = "uvx --from git+https://github.com/minuspervy-art/loosechange loosechange"


def cli_prefix() -> str:
    """How users run the CLI. Read lazily: the bot loads .env after imports.

    Override until the package is on PyPI, e.g.
    LOOSECHANGE_CLI="uvx --from git+https://github.com/minuspervy-art/loosechange loosechange"
    """
    return os.environ.get("LOOSECHANGE_CLI", "").strip() or DEFAULT_CLI


@dataclass
class Snippet:
    target: str
    language: str  # code-block language: yaml / text
    body: str
    command: str | None = None  # one-liner that applies it locally
    copy_text: str | None = None  # what the bot's one-tap "copy" button puts on the clipboard
    notes: dict[str, list[str]] = field(default_factory=dict)  # lang -> lines


class ApplyNotSupported(RuntimeError):
    """The target has no config we can safely write; follow the manual instead."""


def alias_for(profile: str) -> str:
    return f"free-{profile.replace('_', '-')}"


# The bot's command is an explicit choice of this model, so it also replaces the
# current pick of that harness (alias / default model). Backups are made as usual.
CHOOSE_FLAGS = {"hermes": "--force", "deepseek": "--force", "vibeforge": "--make-default"}


def cli_command(model_id: str, target: str, profile: str, apply: bool = False) -> str:
    cmd = f"{cli_prefix()} add {shlex.quote(model_id)} --to {target} --profile {profile}"
    if apply:
        flag = CHOOSE_FLAGS.get(target)
        cmd = f"{cmd} {flag} --apply" if flag else f"{cmd} --apply"
    return cmd


def render_generic(model_id: str, profile: str) -> Snippet:
    body = (
        f"base_url = {OPENROUTER_BASE_URL}\nmodel    = {model_id}\napi_key  = ${OPENROUTER_KEY_ENV}"
    )
    return Snippet(
        target="other",
        language="text",
        body=body,
        copy_text=model_id,
        notes={
            "ru": [
                "Любой OpenAI-совместимый клиент: укажите эти три параметра.",
                "Часть free-моделей (например, thinkingmachines/inkling*) OpenRouter отдаёт "
                "только агентным приложениям из openrouter.ai/apps — в своём клиенте будет 403.",
            ],
            "en": [
                "Any OpenAI-compatible client: set these three values.",
                "Some free models (e.g. thinkingmachines/inkling*) are served only to agentic "
                "apps listed on openrouter.ai/apps — a custom client gets 403.",
            ],
        },
    )
