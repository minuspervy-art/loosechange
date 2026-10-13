"""Access probe: which free models a plain client may call (docs/INTEGRATIONS.md).

OpenRouter serves some free models only to "agentic harnesses" (Hermes, DeepSeek
Harness …) and answers a plain request with 403 "only available on agentic
harnesses". Nothing in /models says so, so we ask each model once, as an ordinary
client (no borrowed app headers), with the user's own key. Only a definite answer is
stored: 200 -> open, that 403 -> harness_only; rate limits and other errors keep the
previous verdict (never invented).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import httpx
from pydantic import BaseModel, Field

from .collect import API, USER_AGENT, _dump, load_snapshot
from .schema import Snapshot

HARNESS_MARKER = "only available on agentic harnesses"
PROMPT = "Reply with exactly one word: ok"


class Access(StrEnum):
    OPEN = "open"  # answers a plain client
    HARNESS_ONLY = "harness_only"  # 403 for a plain client; works in Hermes / DSH


class Outcome(StrEnum):
    OPEN = "open"
    HARNESS_ONLY = "harness_only"
    RATE_LIMITED = "rate_limited"
    ERROR = "error"


class ProbeResult(BaseModel):
    outcome: Outcome
    http: int | None = None
    message: str = ""
    checked_at: datetime


class AccessReport(BaseModel):
    results: dict[str, ProbeResult] = Field(default_factory=dict)

    def verdict(self, model_id: str) -> tuple[Access | None, datetime | None]:
        r = self.results.get(model_id)
        if r and r.outcome in (Outcome.OPEN, Outcome.HARNESS_ONLY):
            return Access(r.outcome.value), r.checked_at
        return None, None


def classify(status: int, body: str) -> Outcome:
    if status == 200:
        return Outcome.OPEN
    if status == 403 and HARNESS_MARKER in body:
        return Outcome.HARNESS_ONLY
    if status == 429:
        return Outcome.RATE_LIMITED
    return Outcome.ERROR


def probe_model(client: httpx.Client, key: str, model_id: str) -> ProbeResult:
    now = datetime.now(UTC)
    try:
        r = client.post(
            f"{API}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "User-Agent": USER_AGENT},
            json={
                "model": model_id,
                "messages": [{"role": "user", "content": PROMPT}],
                "max_tokens": 64,
            },
        )
    except httpx.HTTPError as exc:
        return ProbeResult(outcome=Outcome.ERROR, message=type(exc).__name__, checked_at=now)
    body = r.text.replace(key, "<key>")
    message = ""
    if r.status_code != 200:
        try:
            message = str(json.loads(body).get("error", {}).get("message", ""))[:200]
        except ValueError:
            message = body[:200]
    return ProbeResult(
        outcome=classify(r.status_code, body), http=r.status_code, message=message, checked_at=now
    )


def load_report(path: Path) -> AccessReport:
    if not path.exists():
        return AccessReport()
    return AccessReport.model_validate_json(path.read_text())


def merge(old: AccessReport, new: dict[str, ProbeResult]) -> AccessReport:
    """Definite answers replace old ones; rate limits / errors never erase a verdict."""
    merged = dict(old.results)
    for model_id, r in new.items():
        prev = merged.get(model_id)
        definite = r.outcome in (Outcome.OPEN, Outcome.HARNESS_ONLY)
        prev_definite = prev and prev.outcome in (Outcome.OPEN, Outcome.HARNESS_ONLY)
        if definite or not prev_definite:
            merged[model_id] = r
    return AccessReport(results=merged)


def apply_access(snapshot: Snapshot, report: AccessReport) -> Snapshot:
    for m in snapshot.models:
        m.access, m.access_checked_at = report.verdict(m.id)
    return snapshot


def run(
    data_dir: Path,
    key: str,
    model_ids: Iterable[str] | None = None,
    client: httpx.Client | None = None,
    pause_s: float = 1.0,
    on_result: Callable[[str, ProbeResult], None] | None = None,
) -> AccessReport:
    snap_path = data_dir / "models.json"
    snapshot = load_snapshot(snap_path)
    if snapshot is None:
        raise FileNotFoundError(f"{snap_path} not found: run `loosechange collect` first")
    ids = list(model_ids) if model_ids else [m.id for m in snapshot.models if not m.is_router]
    own = client is None
    client = client or httpx.Client(timeout=90)
    results: dict[str, ProbeResult] = {}
    try:
        for i, model_id in enumerate(ids):
            if i and pause_s:
                time.sleep(pause_s)  # be gentle with free-tier limits
            results[model_id] = probe_model(client, key, model_id)
            if on_result:
                on_result(model_id, results[model_id])
    finally:
        if own:
            client.close()
    report_path = data_dir / "access.json"
    report = merge(load_report(report_path), results)
    _dump(report_path, report)
    _dump(snap_path, apply_access(snapshot, report))
    return report
