"""Collector: OpenRouter `/models` -> free text models -> `data/models.json`.

Benchmarks come only from OpenRouter's built-in `benchmarks` block; a model
without them stays unrated (see docs/RANKING.md). Network failures of the
per-model endpoints call never break the snapshot.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from .schema import (
    Benchmarks,
    DesignArenaEntry,
    Excluded,
    History,
    HistoryEvent,
    Model,
    Reliability,
    Snapshot,
)

log = logging.getLogger(__name__)

API = "https://openrouter.ai/api/v1"
DEFAULT_DATA_DIR = Path("data")
HISTORY_KEEP_DAYS = 90
USER_AGENT = "loosechange (+https://github.com/minuspervy-art/loosechange)"


def _zero(value: Any) -> bool:
    try:
        return float(value) == 0.0
    except (TypeError, ValueError):
        return False


def is_free(raw: dict) -> bool:
    pricing = raw.get("pricing") or {}
    return _zero(pricing.get("prompt")) and _zero(pricing.get("completion"))


def exclusion_reason(raw: dict) -> str | None:
    """Free models we still drop: not a text generator (music, image, audio)."""
    out = (raw.get("architecture") or {}).get("output_modalities") or []
    if "text" not in out:
        return f"no text output ({','.join(out) or 'unknown'})"
    extra = [m for m in out if m != "text"]
    if extra:
        return f"non-text generator ({','.join(out)})"
    return None


def _float(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def parse_benchmarks(raw: dict) -> Benchmarks:
    b = raw.get("benchmarks") or {}
    aa = b.get("artificial_analysis") or {}
    arena = []
    for e in b.get("design_arena") or []:
        if isinstance(e, dict) and e.get("arena") and e.get("category"):
            arena.append(DesignArenaEntry.model_validate(e))
    return Benchmarks(
        intelligence=_float(aa.get("intelligence_index")),
        coding=_float(aa.get("coding_index")),
        agentic=_float(aa.get("agentic_index")),
        design_arena=arena,
    )


def normalize(raw: dict) -> Model:
    arch = raw.get("architecture") or {}
    top = raw.get("top_provider") or {}
    desc = (raw.get("description") or "").strip()
    model_id = raw["id"]
    return Model(
        id=model_id,
        name=raw.get("name") or model_id,
        description=desc[:300],
        context_length=int(raw.get("context_length") or top.get("context_length") or 0),
        max_completion_tokens=top.get("max_completion_tokens"),
        input_modalities=arch.get("input_modalities") or [],
        output_modalities=arch.get("output_modalities") or [],
        supported_parameters=sorted(raw.get("supported_parameters") or []),
        created=raw.get("created"),
        expiration_date=raw.get("expiration_date") or None,
        knowledge_cutoff=raw.get("knowledge_cutoff"),
        is_free_variant=model_id.endswith(":free"),
        is_router=model_id.startswith("openrouter/"),
        benchmarks=parse_benchmarks(raw),
    )


def aggregate_endpoints(endpoints: Iterable[dict]) -> Reliability:
    """OpenRouter routes to the best provider, so take the best value per metric."""
    eps = list(endpoints)

    def best(key: str, fn=max) -> float | None:
        vals = [_float(e.get(key)) for e in eps]
        vals = [v for v in vals if v is not None]
        return fn(vals) if vals else None

    return Reliability(
        uptime_30m=best("uptime_last_30m"),
        uptime_1d=best("uptime_last_1d"),
        latency_30m=best("latency_last_30m", min),
        throughput_30m=best("throughput_last_30m"),
        providers=len(eps),
    )


def build_snapshot(
    raw_models: list[dict],
    endpoints: dict[str, list[dict]] | None = None,
    previous: Snapshot | None = None,
    now: datetime | None = None,
    reuse_reliability: bool = False,
) -> Snapshot:
    """`endpoints` given -> fresh uptime (reliability_at = now). With `reuse_reliability`
    (quick list-only refresh) known models keep the previous uptime and timestamp."""
    now = now or datetime.now(UTC)
    endpoints = endpoints or {}
    prev = {m.id: m for m in previous.models} if previous else {}
    prev_seen = {i: m.first_seen for i, m in prev.items()}
    models: list[Model] = []
    excluded: list[Excluded] = []
    for raw in raw_models:
        if not raw.get("id") or not is_free(raw):
            continue
        reason = exclusion_reason(raw)
        if reason:
            excluded.append(Excluded(id=raw["id"], reason=reason))
            continue
        m = normalize(raw)
        if m.id in endpoints:
            m.reliability = aggregate_endpoints(endpoints[m.id])
        elif reuse_reliability and m.id in prev:
            m.reliability = prev[m.id].reliability
        m.first_seen = prev_seen.get(m.id) or now
        models.append(m)
    models.sort(key=lambda m: m.id)
    if reuse_reliability:
        reliability_at = previous.reliability_at if previous else None
    else:
        reliability_at = now if endpoints else None
    return Snapshot(
        generated_at=now,
        reliability_at=reliability_at,
        total_models=len(raw_models),
        models=models,
        excluded=excluded,
    )


def diff(previous: Snapshot | None, current: Snapshot) -> HistoryEvent | None:
    if previous is None:
        return None
    old = {m.id for m in previous.models}
    new = {m.id for m in current.models}
    if old == new:
        return None
    return HistoryEvent(ts=current.generated_at, added=sorted(new - old), removed=sorted(old - new))


# ---------------------------------------------------------------- IO


def fetch_models(client: httpx.Client) -> list[dict]:
    r = client.get(f"{API}/models")
    r.raise_for_status()
    return r.json()["data"]


def fetch_endpoints(client: httpx.Client, model_id: str) -> list[dict] | None:
    try:
        r = client.get(f"{API}/models/{quote(model_id, safe='/:')}/endpoints")
        r.raise_for_status()
        return (r.json().get("data") or {}).get("endpoints") or []
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("endpoints for %s unavailable: %s", model_id, exc)
        return None


def load_snapshot(path: Path) -> Snapshot | None:
    if not path.exists():
        return None
    try:
        return Snapshot.model_validate_json(path.read_text())
    except ValueError as exc:
        log.warning("ignoring unreadable snapshot %s: %s", path, exc)
        return None


def load_history(path: Path) -> History:
    if not path.exists():
        return History()
    return History.model_validate_json(path.read_text())


def _dump(path: Path, obj) -> None:
    """Atomic write: the bot may be reading the file at the same moment."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = obj.model_dump(mode="json", exclude_none=False)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    os.replace(tmp, path)


def collect(
    data_dir: Path = DEFAULT_DATA_DIR,
    client: httpx.Client | None = None,
    with_endpoints: bool = True,
) -> tuple[Snapshot, HistoryEvent | None]:
    """Full refresh: model list + per-model /endpoints (uptime). ~1 + N requests."""
    own = client is None
    client = client or httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT})
    try:
        raw = fetch_models(client)
        endpoints: dict[str, list[dict]] = {}
        if with_endpoints:
            for r in raw:
                if is_free(r) and not exclusion_reason(r):
                    eps = fetch_endpoints(client, r["id"])
                    if eps is not None:
                        endpoints[r["id"]] = eps
    finally:
        if own:
            client.close()
    return _persist(data_dir, raw, endpoints, reuse_reliability=not with_endpoints)


def quick_collect(
    data_dir: Path = DEFAULT_DATA_DIR, client: httpx.Client | None = None
) -> tuple[Snapshot, HistoryEvent | None]:
    """List-only refresh (1 request): catches added/removed free models fast and keeps
    the last known uptime for models that are still there."""
    own = client is None
    client = client or httpx.Client(timeout=15, headers={"User-Agent": USER_AGENT})
    try:
        raw = fetch_models(client)
    finally:
        if own:
            client.close()
    return _persist(data_dir, raw, {}, reuse_reliability=True)


def _persist(
    data_dir: Path, raw: list[dict], endpoints: dict[str, list[dict]], reuse_reliability: bool
) -> tuple[Snapshot, HistoryEvent | None]:
    snap_path = data_dir / "models.json"
    hist_path = data_dir / "history" / "changes.json"
    previous = load_snapshot(snap_path)
    snapshot = build_snapshot(raw, endpoints, previous, reuse_reliability=reuse_reliability)
    from .probe import apply_access, load_report  # local: probe imports this module

    apply_access(snapshot, load_report(data_dir / "access.json"))
    event = diff(previous, snapshot)

    history = load_history(hist_path)
    if event:
        history.events.append(event)
    cutoff = snapshot.generated_at - timedelta(days=HISTORY_KEEP_DAYS)
    history.events = [e for e in history.events if e.ts >= cutoff]

    _dump(snap_path, snapshot)
    _dump(hist_path, history)
    return snapshot, event


def main() -> None:  # pragma: no cover - thin wrapper
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    snap, event = collect()
    rated = sum(m.benchmarks.has_any for m in snap.models)
    print(f"{len(snap.models)} free text models ({rated} rated), {len(snap.excluded)} excluded")
    if event:
        print(f"added: {event.added} removed: {event.removed}")


if __name__ == "__main__":  # pragma: no cover
    main()
