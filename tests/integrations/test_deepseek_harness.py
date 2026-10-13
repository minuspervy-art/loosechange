import stat

import pytest
from ruamel.yaml import YAML

from loosechange import integrations
from loosechange.integrations import deepseek_harness as dsh
from loosechange.integrations.files import ConfigConflict

MID = "thinkingmachines/inkling-small:free"
MID2 = "nvidia/nemotron-3-super-120b-a12b:free"
KEY = "sk-or-v1-" + "0123456789abcdef" * 4

# exactly what the desktop app ships in ~/.dsh/profiles/desktop/cordis.patch.yml
APP_DEFAULT = (
    "# Your patch layer for this dsh profile, applied after every bundle layer:\n"
    "# a top-level YAML array of loader patch entries (id-targeted config\n"
    "# overrides, disables, and insert lists; `!!js` expressions allowed).\n"
    "[]\n"
)


def load(text):
    return YAML(typ="rt").load(text)


@pytest.fixture
def home(tmp_path):
    p = tmp_path / "profiles" / "desktop" / "cordis.patch.yml"
    p.parent.mkdir(parents=True)
    p.write_text(APP_DEFAULT)
    p.chmod(0o600)
    return tmp_path


def entry(data, entry_id):
    return next(e for e in data if e["id"] == entry_id)


def test_render_snippet_and_target_registration():
    s = integrations.render("deepseek", MID, "agent")
    assert s.target == "deepseek" and s.language == "yaml"
    assert "id: llm-pi-ai" in s.body and "id: agent-default-model" in s.body
    assert f'model: "{MID}"' in s.body
    assert s.command.endswith("--to deepseek --profile agent --apply")
    assert s.copy_text == s.command
    assert "deepseek" in integrations.TARGETS


def test_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("DSH_HOME", str(tmp_path))
    assert dsh.patch_path() == tmp_path / "profiles" / "desktop" / "cordis.patch.yml"
    assert dsh.patch_path("web").parts[-2] == "web"
    monkeypatch.delenv("DSH_HOME")
    assert dsh.dsh_home().name == ".dsh"


def test_plan_on_app_default_keeps_header(home):
    path = dsh.patch_path(home=home)
    p = dsh.plan(MID, path)
    assert path.read_text() == APP_DEFAULT  # plan never writes
    assert p.after.startswith(APP_DEFAULT.splitlines(keepends=True)[0])
    data = load(p.after)
    prov = entry(data, "llm-pi-ai")["config"]["providers"]["openrouter"]
    assert prov["baseURL"] == "https://openrouter.ai/api/v1"
    assert prov["apiKeyEnv"] == "OPENROUTER_API_KEY"
    assert [m["id"] for m in prov["models"]] == [MID]
    assert dict(entry(data, "agent-default-model")["config"]) == {
        "provider": "openrouter",
        "model": MID,
    }
    assert "[{" not in p.after  # block style, not flow


def test_write_backup_mode_and_idempotency(home):
    path = dsh.patch_path(home=home)
    backup = dsh.write(dsh.plan(MID, path))
    assert backup.read_text() == APP_DEFAULT
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    again = dsh.plan(MID, path)
    assert not again.changed and len(again.warnings) == 2


def test_merge_keeps_other_providers_entries_and_js(home):
    path = dsh.patch_path(home=home)
    path.write_text(
        "# mine\n"
        "- id: llm-pi-ai\n"
        "  config:\n"
        "    providers:\n"
        "      local:\n"
        "        baseURL: http://127.0.0.1:1234/v1\n"
        "        models:\n"
        "          - id: qwen\n"
        "      openrouter:\n"
        "        apiKeyEnv: MY_OR_KEY\n"
        "        models:\n"
        f"          - id: {MID2}\n"
        "- id: config-editor\n"
        "  disabled: !!js '!ctx.get(''profileContext'')'\n"
    )
    p = dsh.plan(MID, path)
    data = load(p.after)
    providers = entry(data, "llm-pi-ai")["config"]["providers"]
    assert [m["id"] for m in providers["local"]["models"]] == ["qwen"]  # untouched
    assert [m["id"] for m in providers["openrouter"]["models"]] == [MID2, MID]  # appended
    assert providers["openrouter"]["apiKeyEnv"] == "MY_OR_KEY"  # user's choice kept
    assert "!!js" in p.after and "# mine" in p.after
    assert entry(data, "agent-default-model")["config"]["model"] == MID


def test_default_model_conflict_and_force(home):
    path = dsh.patch_path(home=home)
    path.write_text(
        "- id: agent-default-model\n  config:\n    provider: deepseek-official\n"
        "    model: deepseek-flash\n    reasoningEffort: high\n"
    )
    with pytest.raises(ConfigConflict, match="--force"):
        dsh.plan(MID, path)
    p = dsh.plan(MID, path, force=True)
    cfg = entry(load(p.after), "agent-default-model")["config"]
    assert dict(cfg) == {"provider": "openrouter", "model": MID, "reasoningEffort": "high"}


def test_refuses_expressions_and_non_list(home):
    path = dsh.patch_path(home=home)
    path.write_text("- id: llm-pi-ai\n  config: !!js 'ctx.get(\"x\")'\n")
    with pytest.raises(ConfigConflict, match="expression"):
        dsh.plan(MID, path)
    path.write_text("a: 1\n")
    with pytest.raises(ConfigConflict, match="YAML list"):
        dsh.plan(MID, path)


def test_new_file_gets_header(tmp_path):
    path = tmp_path / "profiles" / "p" / "cordis.patch.yml"
    p = dsh.plan(MID, path)
    assert p.after.startswith("# Your patch layer")
    assert dsh.write(p) is None and stat.S_IMODE(path.stat().st_mode) == 0o600


def test_key_goes_to_dsh_home_env(home, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    path = dsh.patch_path(home=home)
    assert not dsh.has_openrouter_key(path)
    kp = dsh.plan_key(path, KEY)
    assert kp.path == home / ".env" and KEY not in kp.describe()
    dsh.write(kp)
    assert dsh.has_openrouter_key(path)


def test_smoke_check_without_harness(monkeypatch, home):
    monkeypatch.setattr(dsh, "APP_CLI", home / "missing")
    monkeypatch.setattr(dsh.shutil, "which", lambda _: None)
    assert dsh.smoke_check(dsh.plan(MID, dsh.patch_path(home=home))) is None
