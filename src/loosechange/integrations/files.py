"""Shared file helpers for the adapters: safe writes and the OpenRouter key in `.env`.

The key is read from a local file and written to the target tool's `.env`. It never
leaves the machine and is never printed: output shows only a masked form.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .base import OPENROUTER_KEY_ENV


class ConfigConflict(RuntimeError):
    """The target config cannot be changed safely; the message says what to do."""


class Writable(Protocol):
    path: Path
    before: str
    after: str

    @property
    def changed(self) -> bool: ...


def write_with_backup(p: Writable, now: datetime | None = None) -> Path | None:
    """Backup + atomic write. Returns the backup path (None for a new file).

    New files are created 0600 (mkstemp); existing files keep their mode."""
    if not p.changed:
        return None
    backup = None
    if p.path.exists():
        ts = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
        backup = p.path.with_name(f"{p.path.name}.bak-{ts}")
        shutil.copy2(p.path, backup)
    p.path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.path.parent, prefix=".loosechange-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(p.after)
        if backup:
            shutil.copymode(backup, tmp)
        os.replace(tmp, p.path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return backup


KEY_RE = re.compile(r"sk-or-[A-Za-z0-9_-]{16,}")
_ENV_LINE = re.compile(rf"^\s*(?:export\s+)?{OPENROUTER_KEY_ENV}\s*=(.*)$")


def read_key_file(path: Path) -> str:
    """Find exactly one OpenRouter key (sk-or-…) in any text-ish file (.txt/.env/.rtf)."""
    text = path.read_text(errors="replace")
    keys = set(KEY_RE.findall(text))
    if not keys:
        raise ConfigConflict(f"no OpenRouter key (sk-or-…) found in {path}")
    if len(keys) > 1:
        raise ConfigConflict(f"{path} contains {len(keys)} different OpenRouter keys; keep one")
    return keys.pop()


def mask(key: str) -> str:
    return f"{key[:9]}…{key[-4:]}" if len(key) > 16 else "…"


def has_env_key(env_file: Path) -> bool:
    """Is OPENROUTER_API_KEY set (process env or `env_file`)? Never prints it."""
    if os.environ.get(OPENROUTER_KEY_ENV, "").strip():
        return True
    if not env_file.exists():
        return False
    for line in env_file.read_text(errors="replace").splitlines():
        key, sep, value = line.strip().removeprefix("export ").partition("=")
        if sep and key.strip() == OPENROUTER_KEY_ENV and value.strip().strip("'\""):
            return True
    return False


@dataclass
class KeyPlan:
    path: Path
    before: str
    after: str
    action: str  # add | replace | same
    masked: str

    @property
    def changed(self) -> bool:
        return self.before != self.after

    def describe(self) -> str:
        verb = {"add": "add", "replace": "replace", "same": "keep"}[self.action]
        return f"{self.path}: {verb} {OPENROUTER_KEY_ENV}={self.masked}"


def plan_env_key(env: Path, key: str, replace: bool = False) -> KeyPlan:
    if not KEY_RE.fullmatch(key):
        raise ConfigConflict("the value does not look like an OpenRouter key (sk-or-…)")
    before = env.read_text() if env.exists() else ""
    lines = before.splitlines(keepends=True)
    new_line = f"{OPENROUTER_KEY_ENV}={key}\n"
    for i, line in enumerate(lines):
        m = _ENV_LINE.match(line.rstrip("\n"))
        if not m:
            continue
        current = m.group(1).split(" #", 1)[0].strip().strip("'\"")
        if current == key:
            return KeyPlan(env, before, before, "same", mask(key))
        if current and not replace:
            raise ConfigConflict(
                f"{OPENROUTER_KEY_ENV} is already set in {env} to another key "
                f"({mask(current)}); use --replace-key to overwrite it"
            )
        lines[i] = new_line
        return KeyPlan(env, before, "".join(lines), "replace" if current else "add", mask(key))
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    lines.append(new_line)
    return KeyPlan(env, before, "".join(lines), "add", mask(key))
