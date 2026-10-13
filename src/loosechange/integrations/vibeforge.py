"""VibeForge adapter (macOS app `/Applications/VibeForge.app`, researched on 2.0.16).

Since 2.0.16 the "Settings → Providers → OpenRouter" page stores plain-text rows in
the app's SQLite DB (`data/vibeforge.db`, table `app_settings(key, value, updated_at)`):
`VIBEFORGE_OPENROUTER_MODELS` (custom models, ", "-separated), `VIBEFORGE_OPENROUTER_MODEL`
(default model) and `OPENROUTER_API_KEY`. We write only those rows, only while the app
is closed (it keeps settings in memory and would overwrite us), after a consistent
backup of the DB (SQLite backup API, includes the WAL), in one transaction.
`license-key` and `backend-token` are never touched. Details: docs/INTEGRATIONS.md.

VibeForge's API engine is NOT an agentic harness for OpenRouter (verified 403 for
harness-only models), so the CLI refuses those models without --force.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .base import OPENROUTER_KEY_ENV, Snippet, cli_command
from .files import KEY_RE, ConfigConflict, mask

MANUAL_URL = "docs/guides/vibeforge-manual.md"
MODELS_KEY = "VIBEFORGE_OPENROUTER_MODELS"
MODEL_KEY = "VIBEFORGE_OPENROUTER_MODEL"
APP_MARKER = "/VibeForge.app/Contents/"


def default_db_path() -> Path:
    raw = os.environ.get("VIBEFORGE_DATA_DIR", "").strip()
    base = (
        Path(raw).expanduser()
        if raw
        else Path.home() / "Library" / "Application Support" / "com.vibeforge.app" / "data"
    )
    return base / "vibeforge.db"


def render(model_id: str, profile: str) -> Snippet:
    command = cli_command(model_id, "vibeforge", profile, apply=True)
    body = f"Provider: OpenRouter\nModel:    {model_id}"
    return Snippet(
        target="vibeforge",
        language="text",
        body=body,
        command=command,
        copy_text=command,
        notes={
            "ru": [
                "Сначала закройте VibeForge (⌘Q): команда добавит модель в «Свои модели» "
                "OpenRouter (с бэкапом базы), ключ — через --key-file.",
                "Или вручную: Настройки → Провайдеры → OpenRouter. Новая сессия «через API» "
                "→ 🔑 → OpenRouter → модель.",
                "На движке API VibeForge не считается харнессом: модели 🔒 дадут 403.",
            ],
            "en": [
                "Quit VibeForge first (⌘Q): the command adds the model to OpenRouter custom "
                "models (with a DB backup); the key via --key-file.",
                "Or by hand: Settings → Providers → OpenRouter. New session via API → 🔑 → "
                "OpenRouter → model.",
                "On the API engine VibeForge is not an agentic harness: 🔒 models return 403.",
            ],
        },
    )


def manual(model_id: str) -> str:
    return "\n".join(
        [
            "VibeForge (2.0.16) by hand:",
            "  1. Settings → Providers → OpenRouter: API key; add the model to custom models.",
            "  2. New session «via API» → 🔑 → OpenRouter (otherwise it stays Anthropic).",
            f"  3. Model:    {model_id}",
            "  4. Harness-only models (e.g. thinkingmachines/inkling*) return 403 in VibeForge.",
            f"Full guide: {MANUAL_URL}",
        ]
    )


# ---------------------------------------------------------------- apply


def app_running() -> bool:
    try:
        r = subprocess.run(["pgrep", "-f", APP_MARKER], capture_output=True, text=True)
    except FileNotFoundError:  # not macOS
        return False
    return r.returncode == 0 and bool(r.stdout.strip())


def _is_app_db(path: Path) -> bool:
    try:
        return path.resolve() == default_db_path().resolve()
    except OSError:
        return False


def split_models(value: str | None) -> list[str]:
    return [m.strip() for m in (value or "").replace("\n", ",").split(",") if m.strip()]


@dataclass
class Plan:
    path: Path
    current: dict[str, str | None]
    updates: dict[str, str] = field(default_factory=dict)
    changes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.updates)

    def describe(self) -> str:
        lines = []
        for key, new in self.updates.items():
            old = self.current.get(key)
            if key == OPENROUTER_KEY_ENV:
                old_s = mask(old) if old else "(empty)"
                lines.append(f"  {key}: {old_s} -> {mask(new)}")
            else:
                lines.append(f"  {key}:\n    - {old or '(empty)'}\n    + {new}")
        return f"{self.path} (table app_settings):\n" + "\n".join(lines)


def _read(path: Path) -> dict[str, str | None]:
    if not path.exists():
        raise ConfigConflict(f"{path} not found — is VibeForge installed and started once?")
    con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        cols = [r[1] for r in con.execute("pragma table_info(app_settings)")]
        if cols[:3] != ["key", "value", "updated_at"]:
            raise ConfigConflict(f"unexpected app_settings schema {cols}; edit in the app")
        keys = (MODELS_KEY, MODEL_KEY, OPENROUTER_KEY_ENV)
        rows = dict(
            con.execute(
                f"select key, value from app_settings where key in ({','.join('?' * len(keys))})",
                keys,
            ).fetchall()
        )
    finally:
        con.close()
    return {k: rows.get(k) for k in keys}


def plan(
    model_id: str,
    path: Path | None = None,
    make_default: bool = False,
    key: str | None = None,
    replace_key: bool = False,
) -> Plan:
    """Add one model; it becomes the default only if there is none (or make_default)."""
    path = path or default_db_path()
    current = _read(path)
    default = (current[MODEL_KEY] or "").strip()
    new_default = model_id if (make_default or not default) else None
    return plan_many([model_id], path, new_default, key, replace_key, current=current)


def plan_many(
    add: list[str],
    path: Path | None = None,
    new_default: str | None = None,
    key: str | None = None,
    replace_key: bool = False,
    current: dict[str, str | None] | None = None,
) -> Plan:
    path = path or default_db_path()
    current = current if current is not None else _read(path)
    p = Plan(path=path, current=current)

    models = split_models(current[MODELS_KEY])
    fresh = [m for m in dict.fromkeys(add) if m not in models]
    for m in add:
        if m in models:
            p.warnings.append(f"{m} is already in OpenRouter custom models")
    if fresh:
        p.updates[MODELS_KEY] = ", ".join([*models, *fresh])
        p.changes.extend(f"custom models += {m}" for m in fresh)

    default = (current[MODEL_KEY] or "").strip()
    if new_default is None:
        if default:
            p.warnings.append(f"default model stays {default} (pass --make-default to switch)")
    elif new_default == default:
        p.warnings.append(f"{new_default} is already the default OpenRouter model")
    else:
        p.updates[MODEL_KEY] = new_default
        p.changes.append(f"default model: {default or '(empty)'} -> {new_default}")

    if key is not None:
        if not KEY_RE.fullmatch(key):
            raise ConfigConflict("the value does not look like an OpenRouter key (sk-or-…)")
        old = (current[OPENROUTER_KEY_ENV] or "").strip()
        if old == key:
            p.warnings.append(f"{OPENROUTER_KEY_ENV} already set ({mask(key)})")
        elif old and not replace_key:
            raise ConfigConflict(
                f"VibeForge already has another OpenRouter key ({mask(old)}); "
                "use --replace-key to overwrite it"
            )
        else:
            p.updates[OPENROUTER_KEY_ENV] = key
            p.changes.append(f"{OPENROUTER_KEY_ENV} -> {mask(key)}")
    return p


def current_settings(path: Path | None = None) -> dict[str, str | None]:
    return _read(path or default_db_path())


def write(p: Plan, now: datetime | None = None) -> Path | None:
    """Backup (consistent, includes WAL) + one transaction. Refuses while the app runs."""
    if not p.changed:
        return None
    if _is_app_db(p.path) and app_running():
        raise ConfigConflict("VibeForge is running — quit it (⌘Q) and run the command again")
    ts = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    backup = p.path.with_name(f"{p.path.name}.bak-{ts}")
    src = sqlite3.connect(p.path)
    try:
        dst = sqlite3.connect(backup)
        with dst:
            src.backup(dst)
        dst.close()
        os.chmod(backup, 0o600)
        stamp = int(time.time() * 1000)
        src.execute("begin immediate")
        try:
            for key, value in p.updates.items():
                src.execute(
                    "insert into app_settings(key, value, updated_at) values (?, ?, ?) "
                    "on conflict(key) do update set value = excluded.value, "
                    "updated_at = excluded.updated_at",
                    (key, value, stamp),
                )
            src.execute("commit")
        except BaseException:
            src.execute("rollback")
            raise
    finally:
        src.close()
    after = _read(p.path)
    if any(after.get(k) != v for k, v in p.updates.items()):
        raise ConfigConflict(f"write to {p.path} did not stick; restore {backup}")
    return backup


def smoke_check(p: Plan) -> str:
    after = _read(p.path)
    models = split_models(after[MODELS_KEY])
    return f"custom models: {len(models)}, default: {after[MODEL_KEY] or '(empty)'}"


def has_openrouter_key(path: Path) -> bool:
    try:
        return bool((_read(path)[OPENROUTER_KEY_ENV] or "").strip())
    except ConfigConflict:
        return False


# ---------------------------------------------------------------- app lifecycle (sync --restart)

BUNDLE_ID = "com.vibeforge.app"
# agent statuses that mean "nothing is happening" — anything else counts as busy
IDLE_AGENT = {
    "idle",
    "failed",
    "completed",
    "finished",
    "stopped",
    "cancelled",
    "canceled",
    "error",
    "interrupted",
    "done",
    "paused",
}


def busy_reason(path: Path | None = None) -> str | None:
    """Why quitting VibeForge now would interrupt work (None = safe). Read-only."""
    path = path or default_db_path()
    con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        if "agents" in tables:
            rows = con.execute("select status, count(*) from agents group by status").fetchall()
            busy = {st: n for st, n in rows if (st or "").lower() not in IDLE_AGENT}
            if busy:
                return "agents at work: " + ", ".join(f"{n} {st}" for st, n in busy.items())
        for table in ("queue_items", "autopilot_runs"):
            if table in tables:
                n = con.execute(
                    f"select count(*) from {table} where status = 'running'"  # noqa: S608
                ).fetchone()[0]
                if n:
                    return f"{n} running {table.replace('_', ' ')}"
    finally:
        con.close()
    return None


def quit_app(timeout_s: float = 30.0) -> None:
    """Ask VibeForge to quit like ⌘Q and wait until both processes are gone."""
    subprocess.run(
        ["osascript", "-e", f'tell application id "{BUNDLE_ID}" to quit'],
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    deadline = time.monotonic() + timeout_s
    while app_running():
        if time.monotonic() > deadline:
            raise ConfigConflict("VibeForge did not quit in time; nothing was written")
        time.sleep(0.5)


def launch_app() -> None:
    subprocess.run(["open", "-b", BUNDLE_ID], capture_output=True, text=True, timeout=30)
