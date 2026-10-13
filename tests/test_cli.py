import json

import pytest
from typer.testing import CliRunner

from loosechange.cli import app
from loosechange.core.collect import _dump, build_snapshot
from loosechange.integrations import hermes

runner = CliRunner()


@pytest.fixture
def data(tmp_path, raw_models):
    path = tmp_path / "models.json"
    _dump(path, build_snapshot(raw_models))
    return path


def run(*args):
    return runner.invoke(app, [str(a) for a in args])


def test_list_json(data):
    r = run("list", "--profile", "agent", "--json", "--limit", "3", "--data", data)
    assert r.exit_code == 0, r.output
    rows = json.loads(r.output)
    assert [x["rank"] for x in rows] == [1, 2, 3]
    assert all(x["score"] is not None for x in rows)


def test_list_all_marks_unrated(data):
    r = run("list", "-p", "chat", "-n", "0", "--data", data)
    assert r.exit_code == 0
    assert "unrated" in r.output
    assert "openrouter/free" in r.output


def test_list_unavailable_profile(data):
    r = run("list", "-p", "fast_cheap", "--data", data)
    assert r.exit_code == 2


def test_list_bad_profile(data):
    r = run("list", "-p", "nope", "--data", data)
    assert r.exit_code != 0


def test_show(data):
    r = run("show", "thinkingmachines/inkling", "--data", data)
    assert r.exit_code == 0
    assert json.loads(r.output)["id"] == "thinkingmachines/inkling:free"
    assert run("show", "x/y", "--data", data).exit_code == 1


def test_add_hermes_dry_run_then_apply(data, tmp_path, monkeypatch):
    monkeypatch.setattr(hermes.shutil, "which", lambda _: None)  # no smoke check in tests
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model:\n  default: x\n")
    mid = "thinkingmachines/inkling:free"
    r = run("add", mid, "--to", "hermes", "--config", cfg, "--data", data)
    assert r.exit_code == 0, r.output
    assert "+model_aliases:" in r.output and "dry run" in r.output
    assert cfg.read_text() == "model:\n  default: x\n"

    r = run("add", mid, "--to", "hermes", "--config", cfg, "--data", data, "--apply")
    assert r.exit_code == 0, r.output
    assert "backup" in r.output
    assert "free-agent" in cfg.read_text()
    assert list(tmp_path.glob("config.yaml.bak-*"))

    r = run(
        "add",
        "google/gemma-4-31b-it:free",
        "--to",
        "hermes",
        "--config",
        cfg,
        "--data",
        data,
        "--apply",
    )
    assert r.exit_code == 1
    assert "--force" in r.output


def test_add_warns_on_non_free_model(data, tmp_path):
    cfg = tmp_path / "config.yaml"
    r = run("add", "openai/gpt-4o-mini", "--to", "hermes", "--config", cfg, "--data", data)
    assert "not in the free model list" in r.output


def test_add_vibeforge_prints_manual(data):
    r = run("add", "thinkingmachines/inkling:free", "--to", "vibeforge", "--data", data)
    assert r.exit_code == 0
    assert "Providers → OpenRouter" in r.output and "403" in r.output
    assert "vibeforge-manual.md" in r.output


def test_add_other_and_bad_target(data):
    r = run("add", "thinkingmachines/inkling:free", "--to", "other", "--data", data)
    assert "base_url = https://openrouter.ai/api/v1" in r.output
    assert run("add", "x", "--to", "nowhere", "--data", data).exit_code != 0


def test_collect_cmd(tmp_path, monkeypatch, or_transport):
    import httpx

    import loosechange.core.collect as c

    real_client = httpx.Client
    monkeypatch.setattr(c.httpx, "Client", lambda **kw: real_client(transport=or_transport))
    r = run("collect", "--data-dir", tmp_path)
    assert r.exit_code == 0, r.output
    assert "free text models" in r.output
    assert (tmp_path / "models.json").exists()


def test_add_with_key_file_never_prints_key(data, tmp_path, monkeypatch):
    monkeypatch.setattr(hermes.shutil, "which", lambda _: None)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    key = "sk-or-v1-" + "ab" * 32
    key_file = tmp_path / "or.rtf"
    key_file.write_text(r"{\rtf1 " + key + r"\par}")
    home = tmp_path / "hermes"
    home.mkdir()
    cfg = home / "config.yaml"
    cfg.write_text("model:\n  default: x\n")
    (home / ".env").write_text("OTHER=1\n")
    mid = "thinkingmachines/inkling:free"
    base = ["add", mid, "--to", "hermes", "--config", cfg, "--data", data, "--key-file", key_file]

    r = run(*base)  # dry run
    assert r.exit_code == 0, r.output
    assert key not in r.output and "sk-or-v1-…abab" in r.output
    assert (home / ".env").read_text() == "OTHER=1\n"

    r = run(*base, "--apply")
    assert r.exit_code == 0, r.output
    assert key not in r.output
    assert f"OPENROUTER_API_KEY={key}\n" in (home / ".env").read_text()
    assert list(home.glob(".env.bak-*"))
    assert "not set for Hermes" not in r.output

    r = run(*base, "--apply")  # idempotent
    assert "nothing to change" in r.output

    other = tmp_path / "other.txt"
    other.write_text("sk-or-v1-" + "cd" * 32)
    r = run(*[a if a != key_file else other for a in base], "--apply")
    assert r.exit_code == 1 and "--replace-key" in r.output
    assert key not in r.output


def test_add_hints_key_file_when_missing(data, tmp_path, monkeypatch):
    monkeypatch.setattr(hermes.shutil, "which", lambda _: None)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    cfg = tmp_path / "config.yaml"
    r = run(
        "add",
        "thinkingmachines/inkling:free",
        "--to",
        "hermes",
        "--config",
        cfg,
        "--data",
        data,
        "--apply",
    )
    assert r.exit_code == 0 and "--key-file" in r.output


def test_add_deepseek_dry_run_then_apply(data, tmp_path, monkeypatch):
    from loosechange.integrations import deepseek_harness

    monkeypatch.setattr(deepseek_harness, "smoke_check", lambda p: "default model -> ok")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "dsh"))
    key = "sk-or-v1-" + "ef" * 32
    kf = tmp_path / "k.txt"
    kf.write_text(key)
    mid = "thinkingmachines/inkling:free"
    base = ["add", mid, "--to", "deepseek", "--data", data, "--key-file", kf]
    r = run(*base)
    assert r.exit_code == 0, r.output
    assert "+- id: agent-default-model" in r.output and key not in r.output
    patch = tmp_path / "dsh" / "profiles" / "desktop" / "cordis.patch.yml"
    assert not patch.exists()
    r = run(*base, "--apply")
    assert r.exit_code == 0, r.output
    assert "smoke check: default model -> ok" in r.output and key not in r.output
    assert mid in patch.read_text()
    assert f"OPENROUTER_API_KEY={key}" in (tmp_path / "dsh" / ".env").read_text()
    r = run(*base, "--apply", "--dsh-profile", "web")
    assert (tmp_path / "dsh" / "profiles" / "web" / "cordis.patch.yml").exists()
