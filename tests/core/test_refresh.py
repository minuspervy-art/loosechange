import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from loosechange.core.collect import _dump, build_snapshot, collect, load_snapshot, quick_collect
from loosechange.core.refresh import Due, Refresher, RefreshPolicy, due, next_refresh_at

T0 = datetime(2026, 10, 13, 12, tzinfo=UTC)
POLICY = RefreshPolicy(timedelta(minutes=15), timedelta(minutes=60))


def snap_at(raw_models, generated, reliability):
    s = build_snapshot(raw_models, now=generated)
    s.reliability_at = reliability
    return s


@pytest.mark.parametrize(
    "age_list,age_full,expected",
    [
        (5, 5, Due.NONE),
        (16, 30, Due.QUICK),
        (16, 61, Due.FULL),
        (5, 61, Due.FULL),  # uptime expired even though the list is fresh
        (5, None, Due.FULL),  # never collected uptime
    ],
)
def test_due_matrix(raw_models, age_list, age_full, expected):
    rel = None if age_full is None else T0 - timedelta(minutes=age_full)
    s = snap_at(raw_models, T0 - timedelta(minutes=age_list), rel)
    assert due(s, POLICY, T0) is expected


def test_due_without_snapshot_and_disabled_timers(raw_models):
    assert due(None, POLICY, T0) is Due.FULL
    off = RefreshPolicy.from_minutes(0, 0)
    assert not off.enabled
    assert due(snap_at(raw_models, T0 - timedelta(days=9), None), off, T0) is Due.NONE
    list_only = RefreshPolicy.from_minutes(15, 0)
    s = snap_at(raw_models, T0 - timedelta(minutes=20), None)
    assert due(s, list_only, T0) is Due.QUICK


def test_next_refresh_at(raw_models):
    s = snap_at(raw_models, T0, T0 - timedelta(minutes=50))
    assert next_refresh_at(s, POLICY) == T0 - timedelta(minutes=50) + timedelta(minutes=60)


def test_quick_collect_keeps_uptime_and_tracks_changes(tmp_path, raw_models, or_transport):
    client = httpx.Client(transport=or_transport)
    full, _ = collect(tmp_path, client=client)
    assert full.reliability_at == full.generated_at
    inkling = full.get("thinkingmachines/inkling:free").reliability
    assert inkling is not None

    # a free model disappears from the list between refreshes
    gone = "google/gemma-4-31b-it:free"

    def handler(request):
        data = [m for m in raw_models if m["id"] != gone]
        return httpx.Response(200, json={"data": data})

    quick, event = quick_collect(
        tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert quick.generated_at > full.generated_at
    assert quick.reliability_at == full.reliability_at  # uptime not re-fetched
    assert quick.get("thinkingmachines/inkling:free").reliability == inkling  # carried over
    assert quick.get(gone) is None
    assert event is not None and event.removed == [gone]
    history = json.loads((tmp_path / "history" / "changes.json").read_text())
    assert history["events"][-1]["removed"] == [gone]
    assert not list(tmp_path.glob(".*.tmp"))  # atomic writes leave no temp files


class Calls:
    def __init__(self, tmp_path, raw_models, clock):
        self.tmp_path, self.raw, self.clock = tmp_path, raw_models, clock
        self.kinds: list[str] = []

    def quick(self, data_dir):
        self.kinds.append("quick")
        prev = load_snapshot(data_dir / "models.json")
        _dump(data_dir / "models.json", snap_at(self.raw, self.clock(), prev.reliability_at))

    def full(self, data_dir):
        self.kinds.append("full")
        _dump(data_dir / "models.json", snap_at(self.raw, self.clock(), self.clock()))


def make(tmp_path, raw_models, list_age, full_age):
    now = [T0]
    calls = Calls(tmp_path, raw_models, lambda: now[0])
    s = snap_at(raw_models, T0 - timedelta(minutes=list_age), T0 - timedelta(minutes=full_age))
    _dump(tmp_path / "models.json", s)
    r = Refresher(tmp_path, POLICY, quick=calls.quick, full=calls.full, clock=lambda: now[0])
    return r, calls, s


async def test_ensure_fresh_quick_is_awaited(tmp_path, raw_models):
    r, calls, s = make(tmp_path, raw_models, list_age=20, full_age=30)
    assert await r.ensure_fresh(s) is True
    assert calls.kinds == ["quick"]
    assert load_snapshot(tmp_path / "models.json").generated_at == T0
    assert await r.ensure_fresh(load_snapshot(tmp_path / "models.json")) is False  # fresh now


async def test_ensure_fresh_full_runs_in_background_when_list_is_fresh(tmp_path, raw_models):
    r, calls, s = make(tmp_path, raw_models, list_age=5, full_age=90)
    assert await r.ensure_fresh(s) is False  # answer immediately from cache
    await r._full_task
    assert calls.kinds == ["full"]


async def test_ensure_fresh_full_awaited_when_list_expired(tmp_path, raw_models):
    r, calls, s = make(tmp_path, raw_models, list_age=20, full_age=90)
    assert await r.ensure_fresh(s) is True
    assert calls.kinds == ["full"]  # one full refresh, not full + quick


async def test_slow_refresh_times_out_and_failure_is_swallowed(tmp_path, raw_models):
    r, calls, s = make(tmp_path, raw_models, list_age=20, full_age=30)

    def slow(_):
        import time

        time.sleep(0.3)

    r.quick = slow
    assert await r.ensure_fresh(s, timeout=0.05) is False
    await asyncio.sleep(0.4)

    def boom(_):
        raise httpx.ConnectError("offline")

    r.quick = boom
    assert await r.ensure_fresh(s) is False  # logged, cache kept


async def test_store_uses_refresher(tmp_path, raw_models):
    from loosechange.bot.store import DataStore

    r, calls, s = make(tmp_path, raw_models, list_age=20, full_age=30)
    store = DataStore(path=tmp_path / "models.json", refresher=r)
    snap = await store.get()
    assert calls.kinds == ["quick"]
    assert snap.generated_at == T0  # the refreshed file was re-read
