import stat
from datetime import datetime

import pytest
from ruamel.yaml import YAML

from loosechange.integrations import hermes

MID = "nvidia/nemotron-3-ultra-550b-a55b:free"

# Shaped like a real Hermes config (PyYAML-dumped: 80-col folding, indented lists).
CONFIG = """\
model:
  default: gpt-5.6-sol
  provider: openai-codex
  aliases:
    flash: gpt-5.6-luna
providers:
  some-router:
    name: router
    base_url: https://example.invalid/v1
    key_env: SOME_KEY
fallback_providers:
  - provider: custom:some-router
    model: deepseek/deepseek-v4-pro
agent:
  personalities:
    creative: You are a creative assistant. Think outside the box and offer innovative
      solutions.
# trailing comment
_config_version: 33
"""


def load(text):
    return YAML(typ="safe", pure=True).load(text)


@pytest.fixture
def cfg(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(CONFIG)
    p.chmod(0o600)
    return p


def added_lines(plan):
    d = plan.diff().splitlines()
    removed = [line for line in d if line.startswith("-") and not line.startswith("---")]
    assert removed == [], removed
    return [line[1:] for line in d if line.startswith("+") and not line.startswith("+++")]


def test_dry_run_plan_only_adds_lines(cfg):
    plan = hermes.plan(MID, "agent", cfg)
    assert cfg.read_text() == CONFIG  # plan never writes
    assert added_lines(plan) == [
        "model_aliases:",
        "  free-agent:",
        f'    model: "{MID}"',
        "    provider: openrouter",
        "    base_url: https://openrouter.ai/api/v1",
    ]
    data = load(plan.after)
    assert data["model_aliases"]["free-agent"] == hermes.alias_entry(MID)
    assert data["model"]["aliases"] == {"flash": "gpt-5.6-luna"}  # untouched
    assert "# trailing comment" in plan.after
    assert "offer innovative\n      solutions." in plan.after  # no re-folding


def test_fallback_appended_in_existing_list_style(cfg):
    plan = hermes.plan(MID, "agent", cfg, fallback=True)
    lines = added_lines(plan)
    assert "  - provider: openrouter" in lines
    assert f'    model: "{MID}"' in lines
    chain = load(plan.after)["fallback_providers"]
    assert chain[-1] == {"provider": "openrouter", "model": MID}
    assert len(chain) == 2


def test_write_backup_mode_and_idempotency(cfg):
    plan = hermes.plan(MID, "agent", cfg)
    backup = hermes.write(plan, now=datetime(2026, 10, 13, 12, 0, 0))
    assert backup.name == "config.yaml.bak-20261013-120000"
    assert backup.read_text() == CONFIG
    assert stat.S_IMODE(cfg.stat().st_mode) == 0o600
    assert load(cfg.read_text())["model_aliases"]["free-agent"]["model"] == MID
    again = hermes.plan(MID, "agent", cfg)
    assert not again.changed and again.warnings
    assert hermes.write(again) is None


def test_conflict_and_force(cfg):
    hermes.write(hermes.plan(MID, "agent", cfg))
    with pytest.raises(hermes.HermesConflict, match="--force"):
        hermes.plan("google/gemma-4-31b-it:free", "agent", cfg)
    plan = hermes.plan("google/gemma-4-31b-it:free", "agent", cfg, force=True)
    hermes.write(plan)
    data = load(cfg.read_text())
    assert data["model_aliases"]["free-agent"]["model"] == "google/gemma-4-31b-it:free"
    assert cfg.read_text().count("free-agent:") == 1


def test_insert_into_existing_block_keeps_other_aliases(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(
        "model_aliases:\n    qwen:\n        model: q\n        provider: custom\n"
        "# comment\nother: 1\n"
    )
    plan = hermes.plan(MID, "coding", p)
    data = load(plan.after)
    assert set(data["model_aliases"]) == {"qwen", "free-coding"}
    assert "    free-coding:\n" in plan.after  # follows the file's 4-space indent
    assert data["other"] == 1


@pytest.mark.parametrize("inline", ["{}", "null", "~"])
def test_inline_empty_mapping(tmp_path, inline):
    p = tmp_path / "config.yaml"
    p.write_text(f"model_aliases: {inline}\nx: 1\n")
    plan = hermes.plan(MID, "agent", p)
    assert load(plan.after)["model_aliases"] == {"free-agent": hermes.alias_entry(MID)}


def test_flow_style_with_content_is_refused(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("model_aliases: {a: {model: b}}\n")
    with pytest.raises(hermes.HermesConflict, match="flow style"):
        hermes.plan(MID, "agent", p)


def test_missing_and_empty_file(tmp_path):
    p = tmp_path / "new" / "config.yaml"
    plan = hermes.plan(MID, "agent", p)
    assert hermes.write(plan) is None  # nothing to back up
    assert load(p.read_text())["model_aliases"]["free-agent"]["model"] == MID
    e = tmp_path / "empty.yaml"
    e.write_text("")
    assert load(hermes.plan(MID, "agent", e).after)["model_aliases"]


def test_file_without_trailing_newline(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("a: 1")
    plan = hermes.plan(MID, "agent", p, fallback=True)
    data = load(plan.after)
    assert data["a"] == 1 and data["fallback_providers"][0]["model"] == MID


def test_rejects_bad_names(cfg):
    with pytest.raises(hermes.HermesConflict):
        hermes.plan(MID, "agent", cfg, alias="bad alias: x")
    with pytest.raises(hermes.HermesConflict):
        hermes.plan("x\ny: 1", "agent", cfg)


def test_simple_alias_shadow_warning(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("model:\n  aliases:\n    free-agent: openrouter/x\n")
    plan = hermes.plan(MID, "agent", p)
    assert any("model.aliases" in w for w in plan.warnings)


def test_default_config_path(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    assert hermes.default_config_path() == tmp_path / "config.yaml"
    monkeypatch.delenv("HERMES_HOME")
    assert hermes.default_config_path().parts[-2:] == (".hermes", "config.yaml")


def test_smoke_check_without_hermes(monkeypatch, cfg):
    monkeypatch.setattr(hermes.shutil, "which", lambda _: None)
    assert hermes.smoke_check(hermes.plan(MID, "agent", cfg)) is None


def test_has_openrouter_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    cfg = tmp_path / "config.yaml"
    assert not hermes.has_openrouter_key(cfg)
    env = tmp_path / ".env"
    env.write_text("OTHER=1\nOPENROUTER_API_KEY=\n")
    assert not hermes.has_openrouter_key(cfg)  # empty value does not count
    env.write_text('export OPENROUTER_API_KEY="sk-or-test"\n')
    assert hermes.has_openrouter_key(cfg)
    env.unlink()
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    assert hermes.has_openrouter_key(cfg)


def test_render_command_applies():
    s = hermes.render(MID, "agent")
    assert s.command.endswith("--apply") and s.copy_text == s.command
