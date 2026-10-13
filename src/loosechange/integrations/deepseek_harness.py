"""DeepSeek Harness adapter (`/Applications/DeepSeek Harness.app`, `com.deepseek.dsh`).

Researched on 0.2.0-rc.2 (docs/INTEGRATIONS.md):
- the config is a stack of Cordis YAML patch layers; the user layer of a profile is
  `$DSH_HOME/profiles/<profile>/cordis.patch.yml` (DSH_HOME defaults to ~/.dsh) and is
  hot-reloaded by the desktop app (profile `desktop`);
- OpenRouter is wired through the `llm-pi-ai` plugin (`providers.openrouter`), the
  default model through `agent-default-model`; in a patch `config` REPLACES the
  plugin's config wholesale, so we merge into an existing entry ourselves;
- `$DSH_HOME/.env` holds machine-level env defaults (OPENROUTER_API_KEY goes there).
Verified: `thinkingmachines/inkling-small:free` (harness-only on OpenRouter) answers
through `dsh headless` with this overlay.
"""

from __future__ import annotations

import copy
import io
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .base import OPENROUTER_BASE_URL, OPENROUTER_KEY_ENV, Snippet, cli_command
from .files import ConfigConflict, KeyPlan, has_env_key, plan_env_key, write_with_backup

DEFAULT_PROFILE = "desktop"  # the GUI app's profile
APP_CLI = Path("/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh")
PROVIDER = "openrouter"
PI_AI_ID = "llm-pi-ai"
DEFAULT_MODEL_ID = "agent-default-model"
HEADER = (
    "# Your patch layer for this dsh profile, applied after every bundle layer:\n"
    "# a top-level YAML array of loader patch entries (id-targeted config\n"
    "# overrides, disables, and insert lists; `!!js` expressions allowed).\n"
)

write = write_with_backup


def dsh_home() -> Path:
    raw = os.environ.get("DSH_HOME", "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".dsh"


def patch_path(dsh_profile: str = DEFAULT_PROFILE, home: Path | None = None) -> Path:
    return (home or dsh_home()) / "profiles" / dsh_profile / "cordis.patch.yml"


def provider_entry(model_ids: list[str]) -> dict:
    return {
        "displayName": "OpenRouter",
        "api": "openai-completions",
        "baseURL": OPENROUTER_BASE_URL,
        "apiKeyEnv": OPENROUTER_KEY_ENV,
        "models": [{"id": m} for m in model_ids],
    }


def overlay(model_id: str) -> list[dict]:
    """The two patch entries that make `model_id` the harness default via OpenRouter."""
    return [
        {"id": PI_AI_ID, "config": {"providers": {PROVIDER: provider_entry([model_id])}}},
        {"id": DEFAULT_MODEL_ID, "config": {"provider": PROVIDER, "model": model_id}},
    ]


def render(model_id: str, profile: str) -> Snippet:
    body = (
        "# ~/.dsh/profiles/desktop/cordis.patch.yml\n"
        f"- id: {PI_AI_ID}\n"
        "  config:\n"
        "    providers:\n"
        f"      {PROVIDER}:\n"
        "        displayName: OpenRouter\n"
        "        api: openai-completions\n"
        f"        baseURL: {OPENROUTER_BASE_URL}\n"
        f"        apiKeyEnv: {OPENROUTER_KEY_ENV}\n"
        "        models:\n"
        f'          - id: "{model_id}"\n'
        f"- id: {DEFAULT_MODEL_ID}\n"
        "  config:\n"
        f"    provider: {PROVIDER}\n"
        f'    model: "{model_id}"\n'
    )
    command = cli_command(model_id, "deepseek", profile, apply=True)
    return Snippet(
        target="deepseek",
        language="yaml",
        body=body,
        command=command,
        copy_text=command,
        notes={
            "ru": [
                "Команда дописывает это в профиль desktop (с бэкапом); приложение подхватит "
                "без перезапуска. Уже есть другие провайдеры — они сохранятся.",
                f"Ключ: {OPENROUTER_KEY_ENV} в ~/.dsh/.env — допишите к команде "
                "--key-file <файл с ключом>.",
            ],
            "en": [
                "The command adds this to the desktop profile (with a backup); the app picks "
                "it up without a restart. Other providers you have are kept.",
                f"Key: {OPENROUTER_KEY_ENV} in ~/.dsh/.env — "
                "append --key-file <file with the key>.",
            ],
        },
    )


# ---------------------------------------------------------------- apply


def _yaml() -> YAML:
    y = YAML()  # round-trip: keeps the header comments and unknown `!!js` tags
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=2, offset=0)
    return y


def _plain(obj):
    """Comparable plain data (tagged `!!js` scalars become strings)."""
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_plain(v) for v in obj]
    if hasattr(obj, "tag") and hasattr(obj, "value"):  # ruamel TaggedScalar
        return f"{obj.tag.value} {obj.value}"
    return obj


@dataclass
class Plan:
    path: Path
    before: str
    after: str
    changes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.before != self.after

    def diff(self) -> str:
        import difflib

        return "".join(
            difflib.unified_diff(
                self.before.splitlines(keepends=True),
                self.after.splitlines(keepends=True),
                fromfile=str(self.path),
                tofile=f"{self.path} (loosechange)",
            )
        )


def _find(entries: list, entry_id: str):
    return next((e for e in entries if isinstance(e, dict) and e.get("id") == entry_id), None)


def plan(model_id: str, path: Path | None = None, force: bool = False) -> Plan:
    path = path or patch_path()
    before = path.read_text() if path.exists() else ""
    y = _yaml()
    data = y.load(before) if before.strip() else None
    if data is None:
        data = CommentedSeq()
    if not isinstance(data, list):
        raise ConfigConflict(f"{path} must be a YAML list of patch entries")
    if hasattr(data, "fa"):
        data.fa.set_block_style()  # the app writes `[]`; entries go in block style
    original = copy.deepcopy(_plain(data))
    p = Plan(path=path, before=before, after=before)

    # 1) provider: merge our model into llm-pi-ai.providers.openrouter, keep everything else
    pi = _find(data, PI_AI_ID)
    if pi is None:
        entry = CommentedMap(id=PI_AI_ID)
        entry["config"] = CommentedMap(
            providers=CommentedMap({PROVIDER: provider_entry([model_id])})
        )
        data.append(entry)
        p.changes.append(f"{PI_AI_ID}: + provider {PROVIDER} with {model_id}")
    else:
        cfg = pi.get("config")
        if cfg is None:
            cfg = pi["config"] = CommentedMap()
        if not isinstance(cfg, dict):
            raise ConfigConflict(f"{PI_AI_ID}.config is an expression; edit {path} by hand")
        providers = cfg.get("providers")
        if providers is None:
            providers = cfg["providers"] = CommentedMap()
        if not isinstance(providers, dict):
            raise ConfigConflict(f"{PI_AI_ID}.config.providers is an expression; edit by hand")
        prov = providers.get(PROVIDER)
        if prov is None:
            providers[PROVIDER] = provider_entry([model_id])
            p.changes.append(f"{PI_AI_ID}: + provider {PROVIDER} with {model_id}")
        elif not isinstance(prov, dict):
            raise ConfigConflict(f"providers.{PROVIDER} is not a mapping; edit {path} by hand")
        else:
            models = prov.get("models")
            if models is None:
                models = prov["models"] = CommentedSeq()
            if not isinstance(models, list):
                raise ConfigConflict(f"providers.{PROVIDER}.models is not a list")
            ids = [m.get("id") if isinstance(m, dict) else m for m in models]
            if model_id in ids:
                p.warnings.append(f"{PROVIDER} already lists {model_id}")
            else:
                models.append(CommentedMap(id=model_id))
                p.changes.append(f"{PI_AI_ID}: {PROVIDER} models += {model_id}")
            for key, value in provider_entry([]).items():
                if key != "models" and key not in prov:
                    prov[key] = value

    # 2) default model
    dm = _find(data, DEFAULT_MODEL_ID)
    wanted = {"provider": PROVIDER, "model": model_id}
    if dm is None:
        entry = CommentedMap(id=DEFAULT_MODEL_ID)
        entry["config"] = CommentedMap(wanted)
        data.append(entry)
        p.changes.append(f"default model -> {PROVIDER}/{model_id}")
    else:
        cfg = dm.get("config")
        current = {k: cfg.get(k) for k in ("provider", "model")} if isinstance(cfg, dict) else cfg
        if current == wanted:
            p.warnings.append(f"default model is already {PROVIDER}/{model_id}")
        elif force or not isinstance(cfg, dict) or cfg.get("provider") is None:
            new_cfg = CommentedMap(wanted)
            if isinstance(cfg, dict) and cfg.get("reasoningEffort") is not None:
                new_cfg["reasoningEffort"] = cfg["reasoningEffort"]
            dm["config"] = new_cfg
            p.changes.append(f"default model -> {PROVIDER}/{model_id}")
        else:
            raise ConfigConflict(
                f"the default model is set to {cfg.get('provider')}/{cfg.get('model')}; "
                "use --force to replace it"
            )

    if p.changes:
        buf = io.StringIO()
        y.dump(data, buf)
        after = buf.getvalue()
        if not before.strip():
            after = HEADER + after
        elif before.lstrip().startswith("#") and not after.lstrip().startswith("#"):
            # ruamel drops leading comments of an empty `[]` document: keep the header
            head = "".join(
                line for line in before.splitlines(keepends=True) if line.startswith("#")
            )
            after = head + after
        p.after = after
        _verify(original, p, model_id)
    return p


def _verify(original: list, p: Plan, model_id: str) -> None:
    """Every entry we did not touch must be byte-for-byte equal as data."""
    data = _plain(_yaml().load(p.after))
    untouched = lambda entries: [  # noqa: E731
        e
        for e in entries
        if not (isinstance(e, dict) and e.get("id") in (PI_AI_ID, DEFAULT_MODEL_ID))
    ]
    ok = untouched(data) == untouched(original)
    pi = _find(data, PI_AI_ID) or {}
    prov = (((pi.get("config") or {}).get("providers") or {}).get(PROVIDER)) or {}
    ok = ok and any(isinstance(m, dict) and m.get("id") == model_id for m in prov.get("models", []))
    dm = (_find(data, DEFAULT_MODEL_ID) or {}).get("config") or {}
    ok = ok and dm.get("provider") == PROVIDER and dm.get("model") == model_id
    if not ok:
        raise ConfigConflict(f"could not edit {p.path} safely; add the snippet by hand")


def plan_key(path: Path, key: str, replace: bool = False) -> KeyPlan:
    """The key goes to $DSH_HOME/.env (machine-level env defaults of the harness)."""
    return plan_env_key(_home_of(path) / ".env", key, replace=replace)


def has_openrouter_key(path: Path) -> bool:
    return has_env_key(_home_of(path) / ".env")


def _home_of(path: Path) -> Path:
    # <home>/profiles/<profile>/cordis.patch.yml -> <home>
    return path.parent.parent.parent if path.parent.parent.name == "profiles" else path.parent


def smoke_check(p: Plan, timeout: int = 120) -> str | None:
    """Compose the shipped `web` profile (same bundles as `desktop`) with the written
    patch in a throwaway DSH_HOME and confirm the default model resolves to ours.
    None = the harness is not installed. Never touches the user's DSH_HOME."""
    exe = APP_CLI if APP_CLI.exists() else shutil.which("dsh")
    if not exe:
        return None
    with tempfile.TemporaryDirectory(prefix="loosechange-dsh-") as tmp:
        r = subprocess.run(
            [str(exe), "--profile", "web", "--patch", str(p.path), "--dump-config"],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "DSH_HOME": tmp},
        )
    if r.returncode != 0:
        lines = [x for x in r.stderr.splitlines() if "Deprecation" not in x]
        return "error: " + " ".join(lines)[-300:]
    tree = _yaml().load(r.stdout) or []
    dm = (_find(_plain(tree), DEFAULT_MODEL_ID) or {}).get("config") or {}
    return f"default model -> {dm.get('provider')}/{dm.get('model')}"
