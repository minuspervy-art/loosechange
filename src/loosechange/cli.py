"""`loosechange` CLI: list / show / add / collect."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import date
from pathlib import Path
from typing import Annotated

import httpx
import typer

from . import integrations
from .core.collect import (
    DEFAULT_DATA_DIR,
    USER_AGENT,
    build_snapshot,
    collect,
    exclusion_reason,
    fetch_endpoints,
    fetch_models,
    is_free,
    load_snapshot,
)
from .core.profiles import PROFILES, Priority, get_profile
from .core.rank import rank
from .core.schema import Snapshot
from .integrations import deepseek_harness, hermes, vibeforge
from .integrations.files import ConfigConflict, read_key_file, write_with_backup

app = typer.Typer(
    help="Free OpenRouter models ranked by benchmarks; add one to Hermes / VibeForge.",
    no_args_is_help=True,
    add_completion=False,
)

DataOpt = Annotated[
    Path | None,
    typer.Option(
        "--data",
        help="Snapshot JSON. Default: ./data/models.json if present, "
        "else $LOOSECHANGE_DATA_URL, else a live fetch from OpenRouter.",
    ),
]
ProfileOpt = Annotated[str, typer.Option("--profile", "-p", help=f"One of: {', '.join(PROFILES)}")]


def data_candidates() -> list[Path]:
    """Where a local snapshot may live, most specific first. The bot's copied command
    runs from any directory, so ./data alone is not enough: without the project's
    snapshot the harness-only verdicts (access) would be missing."""
    env = os.environ.get("LOOSECHANGE_DATA", "").strip()
    repo = Path(__file__).resolve().parents[2] / "data" / "models.json"  # source checkout
    support = Path.home() / "Library" / "Application Support" / "loosechange" / "data"
    return [
        DEFAULT_DATA_DIR / "models.json",
        *([Path(env).expanduser()] if env else []),
        repo,
        support / "models.json",
    ]


def load_models(data: Path | None) -> Snapshot:
    if data is not None and not data.exists():
        raise typer.BadParameter(f"{data} does not exist", param_hint="--data")
    for path in [data] if data else data_candidates():
        if path.exists():
            snap = load_snapshot(path)
            if snap:
                return snap
    url = os.environ.get("LOOSECHANGE_DATA_URL")
    with httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT}) as client:
        if url:
            r = client.get(url)
            r.raise_for_status()
            return Snapshot.model_validate_json(r.content)
        typer.echo("fetching live data from OpenRouter…", err=True)
        raw = fetch_models(client)
        endpoints = {}
        for r in raw:
            if is_free(r) and not exclusion_reason(r):
                eps = fetch_endpoints(client, r["id"])
                if eps is not None:
                    endpoints[r["id"]] = eps
    snap = build_snapshot(raw, endpoints)
    from .core.probe import apply_access, load_report

    for path in data_candidates():  # keep harness-only verdicts from any local probe
        report = path.parent / "access.json"
        if report.exists():
            return apply_access(snap, load_report(report))
    return snap


def _check_profile(profile: str) -> str:
    try:
        get_profile(profile)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--profile") from None
    return profile


@app.command("list")
def list_cmd(
    profile: ProfileOpt = "agent",
    priority: Annotated[
        Priority, typer.Option("--priority", help="quality | stability | context")
    ] = Priority.QUALITY,
    limit: Annotated[int, typer.Option("--limit", "-n", help="0 = all")] = 10,
    as_json: Annotated[bool, typer.Option("--json")] = False,
    data: DataOpt = None,
) -> None:
    """Rank free models for a task profile."""
    snap = load_models(data)
    result = rank(snap.models, get_profile(_check_profile(profile)), priority, date.today())
    if not result.available:
        typer.echo(f"profile {profile!r} unavailable: {result.reason}", err=True)
        raise typer.Exit(2)
    items = result.all if limit <= 0 else result.all[:limit]
    if as_json:
        out = [
            {
                "rank": s.rank,
                "id": s.model.id,
                "score": s.score,
                "flags": s.flags,
                "context_length": s.model.context_length,
            }
            for s in items
        ]
        typer.echo(json.dumps(out, ensure_ascii=False, indent=1))
        return
    typer.echo(
        f"profile={profile} priority={priority.value} data={snap.generated_at:%Y-%m-%d %H:%M}Z"
    )
    for s in items:
        score = f"{s.score:5.1f}" if s.rated else "  —  "
        b = s.model.benchmarks
        marks = [*s.flags, *(["harness_only"] if s.model.harness_only else [])]
        flags = f"  [{', '.join(marks)}]" if marks else ""
        typer.echo(
            f"{s.rank:>3}. {score}  {s.model.id:<52} "
            f"i={b.intelligence} c={b.coding} a={b.agentic} ctx={s.model.context_length}{flags}"
        )
    if result.unrated and any(s in items for s in result.unrated):
        typer.echo("—  = unrated (no benchmarks on OpenRouter; we never invent scores)")


@app.command()
def show(model_id: str, data: DataOpt = None) -> None:
    """Print one model from the snapshot as JSON."""
    snap = load_models(data)
    m = snap.get(model_id) or snap.get(f"{model_id}:free")
    if not m:
        typer.echo(f"{model_id} is not among free text models", err=True)
        raise typer.Exit(1)
    typer.echo(m.model_dump_json(indent=1))


@app.command()
def add(
    model_id: str,
    to: Annotated[str, typer.Option("--to", help="hermes | vibeforge | deepseek | other")],
    profile: ProfileOpt = "agent",
    alias: Annotated[str | None, typer.Option(help="Hermes alias (default free-<profile>)")] = None,
    fallback: Annotated[
        bool, typer.Option("--fallback", help="Hermes: also append to fallback_providers")
    ] = False,
    config: Annotated[
        Path | None,
        typer.Option(
            help="File to edit. Hermes: config.yaml (default $HERMES_HOME or ~/.hermes); "
            "DeepSeek Harness: cordis.patch.yml (default $DSH_HOME/profiles/<dsh-profile>)"
        ),
    ] = None,
    dsh_profile: Annotated[
        str, typer.Option("--dsh-profile", help="DeepSeek Harness profile (GUI app: desktop)")
    ] = deepseek_harness.DEFAULT_PROFILE,
    dry_run: Annotated[
        bool, typer.Option("--dry-run/--apply", help="Show the diff (default) or write it")
    ] = True,
    force: Annotated[
        bool,
        typer.Option(help="Replace an existing alias / default model; VibeForge: allow 🔒 models"),
    ] = False,
    make_default: Annotated[
        bool,
        typer.Option("--make-default", help="VibeForge: also make it the default OpenRouter model"),
    ] = False,
    key_file: Annotated[
        Path | None,
        typer.Option(
            "--key-file",
            help="File with your OpenRouter key (sk-or-…; txt/.env/.rtf); written to the "
            "tool's .env (Hermes: ~/.hermes/.env, DeepSeek Harness: ~/.dsh/.env), never printed",
        ),
    ] = None,
    replace_key: Annotated[
        bool, typer.Option("--replace-key", help="Overwrite a different existing key")
    ] = False,
    check: Annotated[
        bool, typer.Option("--check/--no-check", help="Verify the id is a free model")
    ] = True,
    data: DataOpt = None,
) -> None:
    """Add a model to Hermes or DeepSeek Harness (writes config with backup), or print
    setup steps for VibeForge / any OpenAI-compatible client."""
    _check_profile(profile)
    if to not in integrations.TARGETS:
        raise typer.BadParameter(
            f"choose from {', '.join(integrations.TARGETS)}", param_hint="--to"
        )
    snap = load_models(data) if check else None
    if snap is not None and not snap.get(model_id):
        typer.secho(
            f"warning: {model_id} is not in the free model list (data from "
            f"{snap.generated_at:%Y-%m-%d %H:%M}Z); it may cost money or not exist",
            fg="yellow",
            err=True,
        )

    if to == "other":
        typer.echo(integrations.render("other", model_id, profile).body)
        return
    if to == "vibeforge":
        _add_vibeforge(model_id, snap, config, make_default, key_file, replace_key, force, dry_run)
        return

    adapter = hermes if to == "hermes" else deepseek_harness
    try:
        if to == "hermes":
            plan = hermes.plan(
                model_id, profile, config, alias=alias, fallback=fallback, force=force
            )
        else:
            path = config or deepseek_harness.patch_path(dsh_profile)
            plan = deepseek_harness.plan(model_id, path, force=force)
        key_plan = None
        if key_file:
            key = read_key_file(key_file.expanduser())
            key_plan = adapter.plan_key(plan.path, key, replace=replace_key)
    except (ConfigConflict, OSError) as exc:
        typer.secho(f"error: {exc}", fg="red", err=True)
        raise typer.Exit(1) from None
    for w in plan.warnings:
        typer.secho(f"note: {w}", fg="yellow", err=True)
    if plan.changed:
        typer.echo(plan.diff())
    if key_plan:
        typer.echo(key_plan.describe())  # masked: sk-or-v1-…abcd
    if not plan.changed and not (key_plan and key_plan.changed):
        typer.echo("nothing to change")
        _key_hint(adapter, plan.path)
        return
    if dry_run:
        typer.echo("dry run: nothing written; re-run with --apply to write (backups are made)")
        return
    for item in (plan, key_plan):
        if item is not None and item.changed:
            backup = write_with_backup(item)
            typer.echo(f"written {item.path}" + (f" (backup: {backup})" if backup else ""))
    if plan.changed:
        try:
            out = adapter.smoke_check(plan)
        except Exception as exc:  # smoke check must never undo a successful write
            out = f"skipped ({exc})"
        if out is not None:
            typer.echo(f"smoke check: {out}")
    if to == "hermes":
        typer.echo(f"use it: hermes -m {plan.alias}")
    else:
        typer.echo(
            "DeepSeek Harness picks the change up without a restart (profile layer is hot-reloaded)"
        )
    _key_hint(adapter, plan.path)


def _add_vibeforge(
    model_id: str,
    snap: Snapshot | None,
    db: Path | None,
    make_default: bool,
    key_file: Path | None,
    replace_key: bool,
    force: bool,
    dry_run: bool,
) -> None:
    model = snap.get(model_id) if snap else None
    if model is not None and model.harness_only and not force:
        typer.secho(
            f"error: {model_id} is served by OpenRouter only to agentic harnesses — "
            "VibeForge's API engine gets 403 (verified). Use Hermes / DeepSeek Harness, "
            "pick another model, or pass --force.",
            fg="red",
            err=True,
        )
        raise typer.Exit(1)
    try:
        key = read_key_file(key_file.expanduser()) if key_file else None
        plan = vibeforge.plan(
            model_id, db, make_default=make_default, key=key, replace_key=replace_key
        )
    except (ConfigConflict, OSError, sqlite3.Error) as exc:
        typer.secho(f"error: {exc}", fg="red", err=True)
        typer.echo(vibeforge.manual(model_id))
        raise typer.Exit(1) from None
    for w in plan.warnings:
        typer.secho(f"note: {w}", fg="yellow", err=True)
    if not plan.changed:
        typer.echo("nothing to change")
        return
    typer.echo(plan.describe())  # the key only masked
    if dry_run:
        typer.echo(
            "dry run: nothing written; quit VibeForge (⌘Q) and re-run with --apply "
            "(the DB is backed up first)"
        )
        return
    try:
        backup = vibeforge.write(plan)
    except (ConfigConflict, sqlite3.Error) as exc:
        typer.secho(f"error: {exc}", fg="red", err=True)
        raise typer.Exit(1) from None
    typer.echo(f"written {plan.path} (backup: {backup})")
    typer.echo(f"smoke check: {vibeforge.smoke_check(plan)}")
    typer.echo("start VibeForge: new session «via API» → 🔑 → OpenRouter → pick the model")


def _key_hint(adapter, config_path: Path) -> None:
    if not adapter.has_openrouter_key(config_path):
        env = (
            config_path.parent / ".env"
            if adapter is hermes
            else deepseek_harness._home_of(config_path) / ".env"
        )
        typer.secho(
            "note: OPENROUTER_API_KEY is not set — add it with --key-file <file> "
            f"or to {env} (key: https://openrouter.ai/keys)",
            fg="yellow",
        )


@app.command()
def probe(
    key_file: Annotated[
        Path, typer.Option("--key-file", help="File with your OpenRouter key (never printed)")
    ],
    model: Annotated[
        list[str] | None, typer.Option("--model", "-m", help="Probe only these ids")
    ] = None,
    data_dir: Annotated[Path, typer.Option("--data-dir")] = DEFAULT_DATA_DIR,
    pause: Annotated[float, typer.Option(help="Seconds between requests")] = 1.0,
) -> None:
    """Ask each free model once, as a plain client, whether it answers (one request per
    model, $0). Marks models OpenRouter serves only to agentic harnesses."""
    from .core import probe as probe_mod

    try:
        key = read_key_file(key_file.expanduser())
    except (ConfigConflict, OSError) as exc:
        typer.secho(f"error: {exc}", fg="red", err=True)
        raise typer.Exit(1) from None
    icons = {
        "open": "✅ open",
        "harness_only": "🔒 harness only",
        "rate_limited": "⏳ 429",
        "error": "❔ error",
    }

    def show(model_id: str, r) -> None:
        extra = f"  ({r.http}: {r.message[:90]})" if r.outcome.value == "error" else ""
        typer.echo(f"{icons[r.outcome.value]:<16} {model_id}{extra}")

    try:
        report = probe_mod.run(data_dir, key, model or None, pause_s=pause, on_result=show)
    except FileNotFoundError as exc:
        typer.secho(f"error: {exc}", fg="red", err=True)
        raise typer.Exit(1) from None
    verdicts = [report.verdict(m)[0] for m in report.results]
    typer.echo(
        f"saved {data_dir / 'access.json'}: {verdicts.count('open')} open, "
        f"{verdicts.count('harness_only')} harness-only, "
        f"{len(verdicts) - verdicts.count('open') - verdicts.count('harness_only')} unknown"
    )


@app.command()
def sync(
    to: Annotated[
        str, typer.Option("--to", help="vibeforge (the only target for now)")
    ] = "vibeforge",
    profile: ProfileOpt = "agent",
    top: Annotated[int, typer.Option(help="How many best models to keep in the list")] = 3,
    data_dir: Annotated[Path, typer.Option("--data-dir")] = DEFAULT_DATA_DIR,
    config: Annotated[Path | None, typer.Option(help="VibeForge DB (default: the app's)")] = None,
    restart: Annotated[
        bool,
        typer.Option(help="Quit VibeForge if it is open (refused while agents work) and reopen"),
    ] = False,
    if_closed: Annotated[
        bool, typer.Option("--if-closed", help="Skip quietly when VibeForge is open (scheduled)")
    ] = False,
    max_age: Annotated[
        int, typer.Option(help="Re-fetch the model list if the snapshot is older (minutes)")
    ] = 60,
    dry_run: Annotated[
        bool, typer.Option("--dry-run/--apply", help="Show the plan (default) or write it")
    ] = True,
) -> None:
    """Keep VibeForge's OpenRouter models current without typing ids: adds the best
    free models a plain client can call; replaces the default only if it broke."""
    from datetime import UTC, datetime, timedelta

    from .core.collect import quick_collect
    from .core.select import choose

    if to != "vibeforge":
        raise typer.BadParameter("only vibeforge is supported", param_hint="--to")
    _check_profile(profile)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    snap_path = data_dir / "models.json"
    snap = load_snapshot(snap_path)
    if snap is None or datetime.now(UTC) - snap.generated_at > timedelta(minutes=max_age):
        try:
            snap, _ = quick_collect(data_dir)
        except Exception as exc:  # offline: use what we have
            typer.secho(f"note: could not refresh the model list ({exc})", fg="yellow", err=True)
    if snap is None:
        typer.secho(f"error: no model data in {data_dir}; run `loosechange collect`", fg="red")
        raise typer.Exit(1)

    try:
        current = vibeforge.current_settings(config)
        sel = choose(snap, current.get(vibeforge.MODEL_KEY), top=top, profile=profile)
        plan = vibeforge.plan_many(
            [m.id for m in sel.picks], config, sel.new_default, current=current
        )
    except (ConfigConflict, OSError, sqlite3.Error) as exc:
        typer.secho(f"[{stamp}] error: {exc}", fg="red", err=True)
        raise typer.Exit(1) from None
    for r in sel.reasons:
        typer.echo(f"note: {r}")
    if not plan.changed:
        typer.echo(
            f"[{stamp}] VibeForge models are up to date ({', '.join(m.id for m in sel.picks)})"
        )
        typer.echo("summary: модели VibeForge актуальны")
        return
    typer.echo(plan.describe())
    if dry_run:
        typer.echo("dry run: nothing written; add --apply (and --restart if VibeForge is open)")
        return

    is_app_db = config is None or vibeforge._is_app_db(config)
    restarted = False
    if is_app_db and vibeforge.app_running():
        if if_closed:
            typer.echo(f"[{stamp}] VibeForge is open — skipped, will try next time")
            typer.echo("summary: VibeForge открыт — обновлю в следующий раз")
            return
        if not restart:
            typer.secho("error: VibeForge is running — quit it (⌘Q) or pass --restart", fg="red")
            raise typer.Exit(1)
        reason = vibeforge.busy_reason(config)
        if reason:
            typer.secho(f"[{stamp}] not restarting VibeForge: {reason}", fg="red")
            typer.echo("summary: в VibeForge идёт работа агентов — не перезапускаю")
            raise typer.Exit(3)
        try:
            vibeforge.quit_app()
        except ConfigConflict as exc:
            typer.secho(f"error: {exc}", fg="red")
            raise typer.Exit(1) from None
        restarted = True
    try:
        backup = vibeforge.write(plan)
        typer.echo(f"[{stamp}] written {plan.path} (backup: {backup})")
        typer.echo(f"smoke check: {vibeforge.smoke_check(plan)}")
        added = [c.split("+= ", 1)[1] for c in plan.changes if "+= " in c]
        summary = f"добавлено {len(added)}: " + ", ".join(a.split("/")[-1] for a in added)
        if sel.new_default:
            summary += f"; по умолчанию {sel.new_default.split('/')[-1]}"
        typer.echo(f"summary: {summary}")
    except (ConfigConflict, sqlite3.Error) as exc:
        typer.secho(f"[{stamp}] error: {exc}", fg="red")
        raise typer.Exit(1) from None
    finally:
        if restarted:
            vibeforge.launch_app()
            typer.echo("VibeForge reopened")


@app.command("collect")
def collect_cmd(
    data_dir: Annotated[Path, typer.Option("--data-dir")] = DEFAULT_DATA_DIR,
    endpoints: Annotated[bool, typer.Option("--endpoints/--no-endpoints")] = True,
) -> None:
    """Refresh data/models.json from OpenRouter."""
    snap, event = collect(data_dir, with_endpoints=endpoints)
    rated = sum(m.benchmarks.has_any for m in snap.models)
    typer.echo(
        f"{len(snap.models)} free text models ({rated} rated), {len(snap.excluded)} excluded"
    )
    if event:
        typer.echo(f"added: {event.added} removed: {event.removed}")


if __name__ == "__main__":  # pragma: no cover
    app()
