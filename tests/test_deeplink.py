import re
from pathlib import Path

import pytest

from loosechange import deeplink, oneclick
from loosechange.core.collect import build_snapshot
from loosechange.integrations import vibeforge as vf

MID = "nvidia/nemotron-3-super-120b-a12b:free"
HARNESS = "thinkingmachines/inkling:free"
SITE = Path(__file__).resolve().parents[1] / "site" / "add.html"


def url(model=MID, to="vibeforge", profile="agent"):
    return deeplink.build(model, to, profile)


def test_build_parse_roundtrip_and_page_url():
    u = url()
    assert u.startswith("loosechange://add?")
    assert deeplink.parse(u) == deeplink.Request(MID, "vibeforge", "agent")
    page = deeplink.page_url("https://me.github.io/loosechange/", MID, "hermes", "coding")
    assert page.startswith("https://me.github.io/loosechange/add.html?model=nvidia%2F")


@pytest.mark.parametrize(
    "bad",
    [
        "https://add?model=a/b&to=hermes&profile=agent",  # wrong scheme
        "loosechange://rm?model=a/b&to=hermes&profile=agent",  # unknown action
        "loosechange://add?model=a/b&to=hermes",  # missing field
        "loosechange://add?model=a/b&to=hermes&profile=agent&key=sk-or-x",  # extra field
        "loosechange://add?model=a/b&model=c/d&to=hermes&profile=agent",  # duplicate
        "loosechange://add?model=a/b;rm -rf ~&to=hermes&profile=agent",  # shell junk
        "loosechange://add?model=../../etc&to=hermes&profile=agent",
        "loosechange://add?model=a/b&to=other&profile=agent",  # nothing to install
        "loosechange://add?model=a/b&to=hermes&profile=admin",
    ],
)
def test_parse_rejects(bad):
    with pytest.raises(ValueError):
        deeplink.parse(bad)


def test_site_page_uses_the_same_rules():
    html = SITE.read_text()
    js_re = re.search(r"const MODEL_RE = /\^(.+)\$/;", html).group(1)
    assert js_re.replace("\\/", "/") == deeplink.MODEL_RE.pattern
    for target in deeplink.TARGETS:
        assert f"{target}:" in html
    assert "textContent" in html and "innerHTML" not in html


@pytest.fixture
def homes(tmp_path, monkeypatch, raw_models):
    from tests.integrations.test_vibeforge import make_db

    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "dsh"))
    db = make_db(tmp_path / "vf", {"VIBEFORGE_OPENROUTER_MODEL": "poolside/laguna-xs-2.1:free"})
    monkeypatch.setenv("VIBEFORGE_DATA_DIR", str(db.parent))
    monkeypatch.setattr(vf, "app_running", lambda: False)
    snap = build_snapshot(raw_models)
    snap.get(HARNESS).access = "harness_only"
    return snap, db


def test_check_then_apply_vibeforge(homes):
    from tests.integrations.test_vibeforge import rows

    snap, db = homes
    status, msg = oneclick.check(url(), snap)
    assert status == oneclick.ASK and "VibeForge" in msg and "бэкап" in msg
    assert rows(db)["VIBEFORGE_OPENROUTER_MODEL"] != MID  # check never writes
    status, msg = oneclick.apply(url(), snap)
    assert status == oneclick.DONE and "Бэкап" in msg
    assert rows(db)["VIBEFORGE_OPENROUTER_MODEL"] == MID  # explicit choice -> default
    assert oneclick.check(url(), snap)[0] == oneclick.DONE  # already installed


def test_hermes_and_deepseek(homes, tmp_path):
    snap, _ = homes
    for to, path in [
        ("hermes", tmp_path / "hermes" / "config.yaml"),
        ("deepseek", tmp_path / "dsh" / "profiles" / "desktop" / "cordis.patch.yml"),
    ]:
        u = url(HARNESS, to)  # harness-only models are fine in real harnesses
        assert oneclick.check(u, snap)[0] == oneclick.ASK
        status, msg = oneclick.apply(u, snap)
        assert status == oneclick.DONE, msg
        assert HARNESS in path.read_text()


def test_refusals(homes, monkeypatch):
    snap, _ = homes
    status, msg = oneclick.check(url(HARNESS, "vibeforge"), snap)
    assert status == oneclick.ERROR and "403" in msg
    status, msg = oneclick.check(url("vendor/gone:free"), snap)
    assert status == oneclick.ERROR and "нет среди бесплатных" in msg
    assert oneclick.check("loosechange://add?model=x", snap)[0] == oneclick.ERROR


def test_vibeforge_open_app_restart_and_busy(homes, monkeypatch):
    snap, _ = homes
    state = {"running": True, "calls": []}
    monkeypatch.setattr(vf, "app_running", lambda: state["running"])
    monkeypatch.setattr(vf, "busy_reason", lambda path=None: None)

    def quit_app(timeout_s=30):
        state["calls"].append("quit")
        state["running"] = False

    monkeypatch.setattr(vf, "quit_app", quit_app)
    monkeypatch.setattr(vf, "launch_app", lambda: state["calls"].append("launch"))
    assert oneclick.check(url(), snap)[0] == oneclick.ASK_RESTART
    assert oneclick.apply(url(), snap)[0] == oneclick.ERROR  # no restart consent
    status, _ = oneclick.apply(url(), snap, restart=True)
    assert status == oneclick.DONE and state["calls"] == ["quit", "launch"]

    state["running"] = True
    monkeypatch.setattr(vf, "busy_reason", lambda path=None: "agents at work: 1 running")
    status, msg = oneclick.check(url("poolside/laguna-xs-2.1:free"), snap)
    assert status == oneclick.ERROR and "агенты" in msg
