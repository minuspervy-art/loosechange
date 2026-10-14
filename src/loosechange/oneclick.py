"""One-click install behind the `loosechange://` link (see deeplink.py).

`check()` says what would change and whether the user must confirm; `apply()` does it.
Both return (status, message) for the handler app:
  ASK          -> confirm, then apply
  ASK_RESTART  -> confirm closing VibeForge, then apply with restart=True
  DONE         -> show the message (nothing left to do)
  ERROR        -> show the message
The link is an explicit choice of the model, so it replaces the harness's current pick
(Hermes alias / default model), exactly like the bot's copied command. Backups as usual.
"""

from __future__ import annotations

import sqlite3

from .core.schema import Snapshot
from .deeplink import Request, parse
from .integrations import deepseek_harness, hermes, vibeforge
from .integrations.files import ConfigConflict, write_with_backup

TITLES = {"hermes": "Hermes", "vibeforge": "VibeForge", "deepseek": "DeepSeek Harness"}
ASK, ASK_RESTART, DONE, ERROR = "ASK", "ASK_RESTART", "DONE", "ERROR"


def _model_line(req: Request, snapshot: Snapshot) -> str:
    m = snapshot.get(req.model)
    return f"{m.name if m else req.model}\n{req.model}"


def _validate(url: str, snapshot: Snapshot) -> Request:
    req = parse(url)
    model = snapshot.get(req.model)
    if model is None:
        raise ConfigConflict(
            f"{req.model} сейчас нет среди бесплатных моделей OpenRouter — "
            "обновите подборку в боте."
        )
    if req.target == "vibeforge" and model.harness_only:
        raise ConfigConflict(
            f"{req.model} OpenRouter отдаёт только агентным харнессам (Hermes, "
            "DeepSeek Harness) — в VibeForge будет ошибка 403. Выберите другую модель."
        )
    return req


def _plan(req: Request):
    if req.target == "hermes":
        return hermes.plan(req.model, req.profile, force=True)
    if req.target == "deepseek":
        return deepseek_harness.plan(req.model, deepseek_harness.patch_path(), force=True)
    return vibeforge.plan(req.model, make_default=True)


def _changes(plan) -> str:
    return "\n".join(f"• {c}" for c in plan.changes)


def check(url: str, snapshot: Snapshot) -> tuple[str, str]:
    try:
        req = _validate(url, snapshot)
        plan = _plan(req)
    except (ValueError, ConfigConflict, OSError, sqlite3.Error) as exc:
        return ERROR, str(exc)
    where = TITLES[req.target]
    if not plan.changed:
        return DONE, f"{_model_line(req, snapshot)}\n\nУже установлена в {where} — менять нечего."
    question = (
        f"Установить в {where}?\n\n{_model_line(req, snapshot)}\n\n{_changes(plan)}\n\n"
        "Перед записью будет сделан бэкап."
    )
    if req.target == "vibeforge" and vibeforge.app_running():
        reason = vibeforge.busy_reason()
        if reason:
            return ERROR, f"В VibeForge сейчас работают агенты ({reason}). Повторите позже."
        return ASK_RESTART, question + "\n\nVibeForge открыт: он закроется и откроется снова."
    return ASK, question


def apply(url: str, snapshot: Snapshot, restart: bool = False) -> tuple[str, str]:
    restarted = False
    try:
        req = _validate(url, snapshot)
        plan = _plan(req)
        if not plan.changed:
            return DONE, f"Уже установлена в {TITLES[req.target]}."
        if req.target == "vibeforge" and vibeforge.app_running():
            if not restart:
                return ERROR, "VibeForge открыт — закройте его (⌘Q) и нажмите ещё раз."
            reason = vibeforge.busy_reason()
            if reason:
                return ERROR, f"В VibeForge сейчас работают агенты ({reason}). Повторите позже."
            vibeforge.quit_app()
            restarted = True
            plan = _plan(req)  # re-read after the app saved its state on quit
        backup = vibeforge.write(plan) if req.target == "vibeforge" else write_with_backup(plan)
    except (ValueError, ConfigConflict, OSError, sqlite3.Error) as exc:
        return ERROR, str(exc)
    finally:
        if restarted:
            vibeforge.launch_app()
    return DONE, _done_message(req, plan, backup)


def _done_message(req: Request, plan, backup) -> str:
    lines = [f"Готово: {req.model} → {TITLES[req.target]}", _changes(plan)]
    if backup:
        lines.append(f"Бэкап: {backup}")
    if req.target == "hermes":
        lines.append(f"Запуск: hermes -m {plan.alias}")
        if not hermes.has_openrouter_key(plan.path):
            lines.append(
                "Нужен OPENROUTER_API_KEY в ~/.hermes/.env (loosechange add … --key-file)."
            )
    elif req.target == "deepseek":
        lines.append("DeepSeek Harness подхватит модель без перезапуска.")
        if not deepseek_harness.has_openrouter_key(plan.path):
            lines.append("Нужен OPENROUTER_API_KEY в ~/.dsh/.env (loosechange add … --key-file).")
    else:
        lines.append("В VibeForge: новая сессия «через API» → 🔑 → OpenRouter.")
        if not vibeforge.has_openrouter_key(plan.path):
            lines.append("Ключ OpenRouter не задан: Настройки → Провайдеры → OpenRouter.")
    return "\n".join(lines)
