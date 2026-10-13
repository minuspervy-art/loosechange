import pytest

from loosechange import integrations
from loosechange.integrations import vibeforge
from loosechange.integrations.base import ApplyNotSupported

MID = "thinkingmachines/inkling:free"


def test_render_is_instructions_only():
    s = integrations.render("vibeforge", MID, "agent")
    assert s.target == "vibeforge"
    assert "Provider: OpenRouter" in s.body and MID in s.body
    assert s.command is None  # nothing to run in a terminal for VibeForge
    assert s.copy_text == MID
    assert s.notes["ru"] and s.notes["en"]


def test_apply_is_refused():
    with pytest.raises(ApplyNotSupported, match="vibeforge-manual"):
        vibeforge.apply(MID, "agent", dry_run=False)


def test_manual_mentions_model_and_guide():
    text = vibeforge.manual(MID)
    assert MID in text and vibeforge.MANUAL_URL in text


def test_render_unknown_target():
    with pytest.raises(ValueError):
        integrations.render("nowhere", MID, "agent")


def test_cli_command_is_shell_quoted():
    s = integrations.render("hermes", "weird id;rm -rf", "agent")
    assert "'weird id;rm -rf'" in s.command


def test_cli_prefix_is_read_lazily(monkeypatch):
    monkeypatch.setenv("LOOSECHANGE_CLI", "uv run --project /x loosechange")
    s = integrations.render("hermes", MID, "agent")
    assert s.command.startswith("uv run --project /x loosechange add ")
    monkeypatch.delenv("LOOSECHANGE_CLI")
    assert integrations.render("hermes", MID, "agent").command.startswith("uvx loosechange add ")
