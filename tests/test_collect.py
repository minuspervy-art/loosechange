from datetime import UTC, datetime, timedelta

import httpx

from loosechange.collect import (
    aggregate_endpoints,
    build_snapshot,
    collect,
    diff,
    exclusion_reason,
    is_free,
    load_history,
    load_snapshot,
    normalize,
)
from loosechange.models import Snapshot

T0 = datetime(2026, 10, 13, 12, tzinfo=UTC)


def by_id(raw_models, model_id):
    return next(r for r in raw_models if r["id"] == model_id)


def test_free_filter_and_exclusions(raw_models):
    snap = build_snapshot(raw_models, now=T0)
    ids = {m.id for m in snap.models}
    assert len(snap.models) >= 15
    assert "openai/gpt-4o-mini" not in ids  # paid
    excluded = {e.id: e.reason for e in snap.excluded}
    assert "google/lyria-3-pro-preview" in excluded  # music generator
    assert "inclusionai/ling-3.1-flash" in ids  # zero-priced non-:free model is kept
    assert all("text" in m.output_modalities for m in snap.models)


def test_is_free_handles_string_variants():
    assert is_free({"pricing": {"prompt": "0", "completion": "0.0"}})
    assert not is_free({"pricing": {"prompt": "0", "completion": "0.000001"}})
    assert not is_free({"pricing": {"prompt": "-1", "completion": "0"}})
    assert not is_free({"pricing": {}})


def test_exclusion_reason():
    assert exclusion_reason({"architecture": {"output_modalities": ["text"]}}) is None
    assert exclusion_reason({"architecture": {"output_modalities": ["image"]}})
    assert exclusion_reason({"architecture": {"output_modalities": ["text", "audio"]}})


def test_normalize_keeps_benchmarks_verbatim(raw_models):
    m = normalize(by_id(raw_models, "thinkingmachines/inkling:free"))
    raw_aa = by_id(raw_models, m.id)["benchmarks"]["artificial_analysis"]
    assert m.benchmarks.intelligence == raw_aa["intelligence_index"]
    assert m.benchmarks.coding == raw_aa["coding_index"]
    assert m.benchmarks.agentic == raw_aa["agentic_index"]
    assert m.benchmarks.design_elo is not None
    assert m.is_free_variant and m.tools and m.reasoning


def test_missing_benchmarks_are_none_not_zero(raw_models):
    m = normalize(by_id(raw_models, "apodex/apodex-1.1-mini:free"))
    assert m.benchmarks.intelligence is None
    assert not m.benchmarks.has_any
    partial = normalize(by_id(raw_models, "inclusionai/ling-3.1-flash"))
    assert partial.benchmarks.intelligence is not None
    assert partial.benchmarks.coding is None


def test_router_flag(raw_models):
    m = normalize(by_id(raw_models, "openrouter/free"))
    assert m.is_router


def test_aggregate_endpoints_best_provider():
    rel = aggregate_endpoints(
        [
            {"uptime_last_30m": 50, "uptime_last_1d": 90, "latency_last_30m": 900},
            {"uptime_last_30m": 99, "uptime_last_1d": None, "latency_last_30m": 300},
        ]
    )
    assert rel.uptime_30m == 99
    assert rel.uptime_1d == 90
    assert rel.latency_30m == 300
    assert rel.throughput_30m is None
    assert rel.providers == 2


def test_first_seen_carried_and_diff(raw_models):
    first = build_snapshot(raw_models[:5], now=T0)
    later = T0 + timedelta(hours=3)
    second = build_snapshot(raw_models[1:7], previous=first, now=later)
    kept = second.get(raw_models[1]["id"])
    assert kept.first_seen == T0
    ev = diff(first, second)
    assert ev is not None
    assert raw_models[0]["id"] in ev.removed
    assert diff(second, second) is None
    assert diff(None, second) is None


def test_collect_end_to_end(tmp_path, or_transport):
    client = httpx.Client(transport=or_transport)
    snap, event = collect(tmp_path, client=client)
    assert event is None  # first run
    stored = load_snapshot(tmp_path / "models.json")
    assert isinstance(stored, Snapshot)
    assert len(stored.models) == len(snap.models) >= 15
    inkling = stored.get("thinkingmachines/inkling:free")
    assert inkling.reliability is not None and inkling.reliability.uptime_30m is not None
    # models without recorded endpoints (404) just have no reliability block
    assert stored.get("liquid/lfm-2.5-2.6b:free").reliability is None
    # second run: no changes -> no history event
    _, event2 = collect(tmp_path, client=client)
    assert event2 is None
    assert load_history(tmp_path / "history" / "changes.json").events == []
