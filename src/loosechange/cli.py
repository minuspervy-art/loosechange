"""`loosechange` CLI: list / show / add / collect."""

from __future__ import annotations

import json
import os
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
from .integrations.base import ApplyNotSupported
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


def load_models(data: Path | None) -> Snapshot:
    path = data or DEFAULT_DATA_DIR / "models.json"
    if path.exists():
        snap = load_snapshot(path)
        if snap:
            return snap
    elif data:
        raise typer.BadParameter(f"{data} does not exist", param_hint="--data")
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
    return build_snapshot(raw, endpoints)


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
        flags = f"  [{', '.join(s.flags)}]" if s.flags else ""
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
    force: Annotated[bool, typer.Option(help="Replace an existing alias / default model")] = False,
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
    if check:
        snap = load_models(data)
        if not snap.get(model_id):
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
        try:
            vibeforge.apply(model_id, profile, dry_run=dry_run)
        except ApplyNotSupported:
            typer.echo(vibeforge.manual(model_id))
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
