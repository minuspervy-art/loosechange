import sqlite3
import stat

import pytest

from loosechange import integrations
from loosechange.integrations import vibeforge as vf
from loosechange.integrations.files import ConfigConflict

MID = "nvidia/nemotron-3-super-120b-a12b:free"
OTHER = "poolside/laguna-xs-2.1:free"
KEY = "sk-or-v1-" + "0123456789abcdef" * 4
KEY2 = "sk-or-v1-" + "fedcba9876543210" * 4


def make_db(tmp_path, rows=None):
    """A DB shaped like VibeForge 2.0.16's (WAL, app_settings + an unrelated table)."""
    path = tmp_path / "data" / "vibeforge.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("pragma journal_mode=wal")
    con.execute(
        "create table app_settings(key text primary key not null, value text not null, "
        "updated_at integer not null)"
    )
    con.execute("create table sessions(id text primary key, provider text)")
    con.execute("insert into sessions values ('s1', 'openrouter')")
    base = {
        "license.key": "LICENSE-SECRET",
        "VIBEFORGE_OPENROUTER_MODELS": OTHER,
        "mcp.enabled": "0",
    }
    for k, v in {**base, **(rows or {})}.items():
        con.execute("insert into app_settings values (?, ?, 1)", (k, v))
    con.commit()
    con.close()
    path.chmod(0o600)
    return path


def rows(path):
    con = sqlite3.connect(path)
    try:
        return dict(con.execute("select key, value from app_settings"))
    finally:
        con.close()


def test_render_has_apply_command():
    s = integrations.render("vibeforge", MID, "agent")
    assert s.target == "vibeforge" and MID in s.body
    assert s.command.endswith("--to vibeforge --profile agent --apply")
    assert s.copy_text == s.command
    assert "⌘Q" in s.notes["ru"][0]


def test_plan_adds_model_and_sets_empty_default(tmp_path):
    db = make_db(tmp_path)
    p = vf.plan(MID, db)
    assert p.updates == {
        "VIBEFORGE_OPENROUTER_MODELS": f"{OTHER}, {MID}",
        "VIBEFORGE_OPENROUTER_MODEL": MID,
    }
    assert rows(db)["VIBEFORGE_OPENROUTER_MODELS"] == OTHER  # plan never writes


def test_default_kept_unless_make_default(tmp_path):
    db = make_db(tmp_path, {"VIBEFORGE_OPENROUTER_MODEL": OTHER})
    p = vf.plan(MID, db)
    assert "VIBEFORGE_OPENROUTER_MODEL" not in p.updates
    assert any("--make-default" in w for w in p.warnings)
    p = vf.plan(MID, db, make_default=True)
    assert p.updates["VIBEFORGE_OPENROUTER_MODEL"] == MID


def test_write_backup_transaction_and_untouched_rows(tmp_path):
    db = make_db(tmp_path)
    p = vf.plan(MID, db, key=KEY)
    assert KEY not in p.describe() and "…" in p.describe()
    backup = vf.write(p)
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert rows(backup)["VIBEFORGE_OPENROUTER_MODELS"] == OTHER  # consistent pre-write copy
    after = rows(db)
    assert after["VIBEFORGE_OPENROUTER_MODELS"] == f"{OTHER}, {MID}"
    assert after["OPENROUTER_API_KEY"] == KEY
    assert after["license.key"] == "LICENSE-SECRET" and after["mcp.enabled"] == "0"
    con = sqlite3.connect(db)
    assert con.execute("select provider from sessions").fetchone() == ("openrouter",)
    con.close()
    again = vf.plan(MID, db, key=KEY)
    assert not again.changed and vf.write(again) is None


def test_key_conflict(tmp_path):
    db = make_db(tmp_path, {"OPENROUTER_API_KEY": KEY})
    with pytest.raises(ConfigConflict, match="--replace-key") as exc:
        vf.plan(MID, db, key=KEY2)
    assert KEY not in str(exc.value) and KEY2 not in str(exc.value)
    assert vf.plan(MID, db, key=KEY2, replace_key=True).updates["OPENROUTER_API_KEY"] == KEY2
    with pytest.raises(ConfigConflict):
        vf.plan(MID, db, key="not-a-key")


def test_refuses_while_app_runs_for_the_app_db(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    monkeypatch.setenv("VIBEFORGE_DATA_DIR", str(db.parent))
    monkeypatch.setattr(vf, "app_running", lambda: True)
    with pytest.raises(ConfigConflict, match="⌘Q"):
        vf.write(vf.plan(MID))
    assert rows(db)["VIBEFORGE_OPENROUTER_MODELS"] == OTHER
    # a copy elsewhere is not the live app DB: writing it is fine
    monkeypatch.delenv("VIBEFORGE_DATA_DIR")
    assert vf.write(vf.plan(MID, db)) is not None


def test_missing_db_and_bad_schema(tmp_path):
    with pytest.raises(ConfigConflict, match="not found"):
        vf.plan(MID, tmp_path / "nope.db")
    bad = tmp_path / "bad.db"
    con = sqlite3.connect(bad)
    con.execute("create table app_settings(k text, v text)")
    con.close()
    with pytest.raises(ConfigConflict, match="schema"):
        vf.plan(MID, bad)


def test_split_models():
    assert vf.split_models("a, b,c\nd,, ") == ["a", "b", "c", "d"]
    assert vf.split_models(None) == []


def test_busy_reason(tmp_path):
    db = make_db(tmp_path)
    con = sqlite3.connect(db)
    con.execute("create table agents(id text, status text)")
    con.execute("create table queue_items(id text, status text)")
    con.execute("insert into agents values ('a', 'failed'), ('b', 'idle')")
    con.commit()
    assert vf.busy_reason(db) is None
    con.execute("insert into agents values ('c', 'running')")
    con.commit()
    assert "1 running" in vf.busy_reason(db)
    con.execute("update agents set status = 'idle'")
    con.execute("insert into queue_items values ('q', 'running')")
    con.commit()
    con.close()
    assert "queue items" in vf.busy_reason(db)


def test_plan_many(tmp_path):
    db = make_db(tmp_path, {"VIBEFORGE_OPENROUTER_MODEL": OTHER})
    p = vf.plan_many([MID, OTHER, MID], db, new_default=None)
    assert p.updates == {"VIBEFORGE_OPENROUTER_MODELS": f"{OTHER}, {MID}"}
    p = vf.plan_many([MID], db, new_default=MID)
    assert p.updates["VIBEFORGE_OPENROUTER_MODEL"] == MID


def test_app_pattern_is_anchored():
    import re

    assert re.search(vf.APP_PATTERN, "/Applications/VibeForge.app/Contents/MacOS/app")
    assert re.search(
        vf.APP_PATTERN, "/Applications/VibeForge.app/Contents/Resources/resources/backend/bin/node"
    )
    assert not re.search(vf.APP_PATTERN, "zsh -c pgrep -f /Applications/VibeForge.app/Contents/")
