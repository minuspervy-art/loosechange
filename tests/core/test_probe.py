import json
from datetime import UTC, datetime

import httpx

from loosechange.core.collect import _dump, build_snapshot, collect, load_snapshot
from loosechange.core.probe import (
    AccessReport,
    Outcome,
    ProbeResult,
    classify,
    merge,
    probe_model,
    run,
)

KEY = "sk-or-v1-" + "ab" * 32
T = datetime(2026, 10, 14, tzinfo=UTC)


def test_classify():
    assert classify(200, "{}") is Outcome.OPEN
    harness = '{"error":{"message":"x:free is only available on agentic harnesses. Try"}}'
    assert classify(403, harness) is Outcome.HARNESS_ONLY
    assert classify(403, '{"error":{"message":"forbidden"}}') is Outcome.ERROR
    assert classify(429, "") is Outcome.RATE_LIMITED
    assert classify(500, "") is Outcome.ERROR


def handler_for(outcomes):
    seen = []

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        seen.append((request.headers, body))
        status, msg = outcomes[body["model"]]
        if status == 200:
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
        return httpx.Response(status, json={"error": {"message": msg + " " + KEY}})

    return handler, seen


def test_probe_is_a_plain_client_and_never_leaks_key():
    handler, seen = handler_for({"a/x:free": (403, "only available on agentic harnesses")})
    r = probe_model(httpx.Client(transport=httpx.MockTransport(handler)), KEY, "a/x:free")
    assert r.outcome is Outcome.HARNESS_ONLY and r.http == 403
    assert KEY not in r.message
    headers, body = seen[0]
    assert "x-title" not in headers and "http-referer" not in headers  # no borrowed identity
    assert body["max_tokens"] <= 64


def test_merge_never_erases_a_verdict():
    old = AccessReport(results={"m": ProbeResult(outcome=Outcome.HARNESS_ONLY, checked_at=T)})
    new = merge(old, {"m": ProbeResult(outcome=Outcome.RATE_LIMITED, http=429, checked_at=T)})
    assert new.verdict("m")[0] == "harness_only"
    new = merge(old, {"m": ProbeResult(outcome=Outcome.OPEN, http=200, checked_at=T)})
    assert new.verdict("m")[0] == "open"
    assert AccessReport().verdict("m") == (None, None)


def test_run_writes_report_and_snapshot_and_collect_keeps_it(tmp_path, raw_models, or_transport):
    snap = build_snapshot(raw_models, now=T)
    _dump(tmp_path / "models.json", snap)
    ids = [
        "thinkingmachines/inkling:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
        "google/gemma-4-31b-it:free",
    ]
    handler, _ = handler_for(
        {
            ids[0]: (403, "only available on agentic harnesses"),
            ids[1]: (200, ""),
            ids[2]: (429, "temporarily rate-limited upstream"),
        }
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))
    report = run(tmp_path, KEY, ids, client=client, pause_s=0)
    assert report.verdict(ids[0])[0] == "harness_only"
    assert report.verdict(ids[1])[0] == "open"
    assert report.verdict(ids[2])[0] is None  # 429 = unknown, not invented
    stored = load_snapshot(tmp_path / "models.json")
    assert stored.get(ids[0]).harness_only and stored.get(ids[1]).access == "open"
    assert stored.get(ids[2]).access is None
    assert KEY not in (tmp_path / "access.json").read_text()
    # a later data refresh keeps the verdicts
    collect(tmp_path, client=httpx.Client(transport=or_transport), with_endpoints=False)
    assert load_snapshot(tmp_path / "models.json").get(ids[0]).harness_only


def test_congestion_recorded_cleared_and_expires():
    from datetime import timedelta

    from loosechange.core.probe import CONGESTION_TTL

    r429 = ProbeResult(outcome=Outcome.RATE_LIMITED, http=429, checked_at=T)
    rep = merge(AccessReport(), {"m": r429})
    rep = merge(rep, {"m": ProbeResult(outcome=Outcome.RATE_LIMITED, checked_at=T + timedelta(1))})
    assert rep.congestion["m"].count == 2
    assert rep.congested_at("m", now=T + timedelta(1)) is not None
    assert rep.congested_at("m", now=T + timedelta(1) + CONGESTION_TTL * 2) is None  # stale
    assert rep.verdict("m") == (None, None)  # 429 is never a verdict
    rep = merge(rep, {"m": ProbeResult(outcome=Outcome.OPEN, http=200, checked_at=T)})
    assert "m" not in rep.congestion and rep.verdict("m")[0] == "open"


def test_record_updates_snapshot(tmp_path, raw_models):
    from loosechange.core.probe import record

    _dump(tmp_path / "models.json", build_snapshot(raw_models, now=T))
    now = datetime.now(UTC)
    record(
        tmp_path,
        {"google/gemma-4-31b-it:free": ProbeResult(outcome=Outcome.RATE_LIMITED, checked_at=now)},
        source="vibeforge-log",
    )
    snap = load_snapshot(tmp_path / "models.json")
    assert snap.get("google/gemma-4-31b-it:free").congested
    assert (
        json.loads((tmp_path / "access.json").read_text())["congestion"][
            "google/gemma-4-31b-it:free"
        ]["source"]
        == "vibeforge-log"
    )
