"""Hermes Agent adapter (~/.hermes/config.yaml).

Verified against Hermes v0.19.1 sources (docs/INTEGRATIONS.md):
- OpenRouter is a built-in provider keyed by OPENROUTER_API_KEY; a `providers.openrouter`
  entry would be shadowed by the built-in, so we do not write one.
- `model.aliases` values are parsed as "<provider>/<model>", which breaks OpenRouter ids
  like `nvidia/x:free`; the dict form `model_aliases.<name>: {model, provider, base_url}`
  is resolved first and is what we write. Use it as `hermes -m <alias>`.
"""

from __future__ import annotations

import copy
import difflib
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ruamel.yaml import YAML

from .base import OPENROUTER_BASE_URL, OPENROUTER_KEY_ENV, Snippet, alias_for, cli_command


def alias_entry(model_id: str) -> dict[str, str]:
    return {"model": model_id, "provider": "openrouter", "base_url": OPENROUTER_BASE_URL}


def render(model_id: str, profile: str) -> Snippet:
    alias = alias_for(profile)
    command = cli_command(model_id, "hermes", profile, apply=True)
    body = (
        "model_aliases:\n"
        f"  {alias}:\n"
        f'    model: "{model_id}"\n'
        "    provider: openrouter\n"
        f"    base_url: {OPENROUTER_BASE_URL}\n"
    )
    return Snippet(
        target="hermes",
        language="yaml",
        body=body,
        command=command,
        copy_text=command,
        notes={
            "ru": [
                "Команда делает бэкап config.yaml; без --apply — только покажет изменения.",
                f"Ключ: {OPENROUTER_KEY_ENV} в ~/.hermes/.env. Запуск: hermes -m {alias}",
                "Free-модели OpenRouter имеют лимиты запросов в минуту и в сутки.",
            ],
            "en": [
                "The command backs up config.yaml; without --apply it only shows the diff.",
                f"Key: {OPENROUTER_KEY_ENV} in ~/.hermes/.env. Run: hermes -m {alias}",
                "OpenRouter free models are rate-limited per minute and per day.",
            ],
        },
    )


# ---------------------------------------------------------------- apply


def default_config_path() -> Path:
    home = os.environ.get("HERMES_HOME", "").strip()
    return (Path(home).expanduser() if home else Path.home() / ".hermes") / "config.yaml"


def _load(text: str):
    """Plain python data (dicts/lists) — used to verify edits semantically."""
    return YAML(typ="safe", pure=True).load(text) if text.strip() else None


class HermesConflict(RuntimeError):
    pass


@dataclass
class Plan:
    path: Path
    alias: str
    before: str
    after: str
    changes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.before != self.after

    def diff(self) -> str:
        return "".join(
            difflib.unified_diff(
                self.before.splitlines(keepends=True),
                self.after.splitlines(keepends=True),
                fromfile=str(self.path),
                tofile=f"{self.path} (loosechange)",
            )
        )


# The edit is textual (Hermes rewrites config.yaml with PyYAML, and any YAML
# re-dump would re-fold unrelated long strings), then verified by parsing.

_TOP_KEY = re.compile(r"^([A-Za-z0-9_][^:#]*):(.*)$")


def _block(lines: list[str], key: str) -> tuple[int, int, str] | None:
    """(key line, end exclusive of the block's last content line + 1, inline value)."""
    for i, line in enumerate(lines):
        m = _TOP_KEY.match(line.rstrip("\n"))
        if m and m.group(1).strip() == key:
            inline = m.group(2).split(" #", 1)[0].strip()
            end = i + 1
            for j in range(i + 1, len(lines)):
                text = lines[j].rstrip("\n")
                if not text.strip():
                    continue
                if not text.startswith((" ", "\t")):
                    if text.startswith("#"):
                        continue  # column-0 comment: belongs to whatever follows
                    break
                end = j + 1
            return i, end, inline
    return None


def _child_indent(lines: list[str], start: int, end: int, default: int = 2) -> int:
    for line in lines[start + 1 : end]:
        text = line.rstrip("\n")
        if text.strip() and not text.lstrip().startswith("#"):
            return len(text) - len(text.lstrip(" "))
    return default


def _ensure_newline(lines: list[str]) -> None:
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"


def _alias_lines(alias: str, model_id: str, ind: int) -> list[str]:
    pad, pad2 = " " * ind, " " * (ind * 2)
    e = alias_entry(model_id)
    return [
        f"{pad}{alias}:\n",
        f'{pad2}model: "{e["model"]}"\n',
        f"{pad2}provider: {e['provider']}\n",
        f"{pad2}base_url: {e['base_url']}\n",
    ]


def _set_alias(lines: list[str], alias: str, model_id: str, replace: bool) -> None:
    blk = _block(lines, "model_aliases")
    if blk is None:
        _ensure_newline(lines)
        lines.extend(["model_aliases:\n", *_alias_lines(alias, model_id, 2)])
        return
    start, end, inline = blk
    if inline and inline not in ("{}", "null", "~"):
        raise HermesConflict("model_aliases uses flow style; edit it by hand")
    if inline:
        lines[start] = "model_aliases:\n"
    ind = _child_indent(lines, start, end)
    if replace:  # drop the existing alias sub-block
        for i in range(start + 1, end):
            if lines[i].rstrip("\n") == f"{' ' * ind}{alias}:":
                j = i + 1
                while j < end and (
                    not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip(" ")) > ind
                ):
                    j += 1
                del lines[i:j]
                end -= j - i
                break
        else:
            raise HermesConflict(f"cannot locate model_aliases.{alias} in block style")
    lines[end:end] = _alias_lines(alias, model_id, ind)


def _add_fallback(lines: list[str], model_id: str) -> None:
    blk = _block(lines, "fallback_providers")
    if blk is None:
        _ensure_newline(lines)
        lines.extend(
            ["fallback_providers:\n", "  - provider: openrouter\n", f'    model: "{model_id}"\n']
        )
        return
    start, end, inline = blk
    if inline and inline not in ("[]", "null", "~"):
        raise HermesConflict("fallback_providers uses flow style; edit it by hand")
    if inline:
        lines[start] = "fallback_providers:\n"
    dash = 2
    for line in lines[start + 1 : end]:
        if line.lstrip().startswith("- "):
            dash = len(line) - len(line.lstrip(" "))
            break
    pad = " " * dash
    lines[end:end] = [f"{pad}- provider: openrouter\n", f'{pad}  model: "{model_id}"\n']


def plan(
    model_id: str,
    profile: str,
    path: Path | None = None,
    alias: str | None = None,
    fallback: bool = False,
    force: bool = False,
) -> Plan:
    path = path or default_config_path()
    alias = alias or alias_for(profile)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", alias):
        raise HermesConflict(f"invalid alias name {alias!r}")
    if not re.fullmatch(r"[A-Za-z0-9~][A-Za-z0-9_.:/~-]*", model_id):
        raise HermesConflict(f"unexpected model id {model_id!r}")
    before = path.read_text() if path.exists() else ""
    data = _load(before)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise HermesConflict(f"{path} is not a YAML mapping")

    p = Plan(path=path, alias=alias, before=before, after=before)
    wanted = alias_entry(model_id)
    expected = copy.deepcopy(data)
    lines = before.splitlines(keepends=True)

    aliases = data.get("model_aliases") or {}
    if not isinstance(aliases, dict):
        raise HermesConflict("model_aliases exists but is not a mapping")
    current = aliases.get(alias)
    if current is None:
        _set_alias(lines, alias, model_id, replace=False)
        p.changes.append(f"model_aliases.{alias} -> {model_id} (openrouter)")
    elif current == wanted:
        p.warnings.append(f"model_aliases.{alias} already points to {model_id}; nothing to do")
    elif force:
        _set_alias(lines, alias, model_id, replace=True)
        old = current.get("model") if isinstance(current, dict) else current
        p.changes.append(f"model_aliases.{alias}: {old} -> {model_id}")
    else:
        old = current.get("model") if isinstance(current, dict) else current
        raise HermesConflict(
            f"model_aliases.{alias} already points to {old!r}; "
            "use --force to replace it or --alias to pick another name"
        )
    if current != wanted:
        expected["model_aliases"] = {**aliases, alias: wanted}

    model_section = data.get("model")
    simple = model_section.get("aliases") if isinstance(model_section, dict) else None
    if isinstance(simple, dict) and alias in simple:
        p.warnings.append(f"model.aliases.{alias} also exists; Hermes resolves model_aliases first")

    if fallback:
        chain = data.get("fallback_providers") or []
        if not isinstance(chain, list):
            raise HermesConflict("fallback_providers exists but is not a list")
        entry = {"provider": "openrouter", "model": model_id}
        if entry in chain:
            p.warnings.append("fallback chain already contains this model")
        else:
            _add_fallback(lines, model_id)
            expected["fallback_providers"] = [*chain, entry]
            p.changes.append(f"fallback_providers += openrouter/{model_id}")

    if p.changes:
        p.after = "".join(lines)
        if _load(p.after) != expected:
            raise HermesConflict(
                "could not edit the file safely (unexpected layout); add the snippet by hand"
            )
    return p


def write(p: Plan, now: datetime | None = None) -> Path | None:
    """Backup + atomic write. Returns the backup path (None for a new file)."""
    if not p.changed:
        return None
    backup = None
    if p.path.exists():
        ts = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
        backup = p.path.with_name(f"{p.path.name}.bak-{ts}")
        shutil.copy2(p.path, backup)
    p.path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.path.parent, prefix=".loosechange-", suffix=".yaml")
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


def has_openrouter_key(config_path: Path) -> bool:
    """Is OPENROUTER_API_KEY set for Hermes (env or <hermes home>/.env)? Never prints it."""
    if os.environ.get(OPENROUTER_KEY_ENV, "").strip():
        return True
    env_file = config_path.parent / ".env"
    if not env_file.exists():
        return False
    for line in env_file.read_text(errors="replace").splitlines():
        key, sep, value = line.strip().removeprefix("export ").partition("=")
        if sep and key.strip() == OPENROUTER_KEY_ENV and value.strip().strip("'\""):
            return True
    return False


def smoke_check(p: Plan, timeout: int = 60) -> str | None:
    """Ask Hermes itself to resolve the alias from the written file (None = hermes absent)."""
    exe = shutil.which("hermes")
    if not exe or p.path.name != "config.yaml":
        return None
    env = {**os.environ, "HERMES_HOME": str(p.path.parent)}
    r = subprocess.run(
        [exe, "config", "get", f"model_aliases.{p.alias}.model"],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    return (r.stdout or r.stderr).strip()
