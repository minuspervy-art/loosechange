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


async def test_kick_never_waits_and_refreshes_in_background(tmp_path, raw_models):
    r, calls, s = make(tmp_path, raw_models, list_age=20, full_age=30)
    assert r.kick(s) is Due.QUICK
    assert calls.kinds == []  # nothing ran synchronously: the answer is not delayed
    assert r.kick(s) is Due.NONE  # no second refresh while one is pending
    await r._task
    assert calls.kinds == ["quick"]
    fresh = load_snapshot(tmp_path / "models.json")
    assert fresh.generated_at == T0
    assert r.kick(fresh) is Due.NONE


async def test_kick_full_when_uptime_expired(tmp_path, raw_models):
    r, calls, s = make(tmp_path, raw_models, list_age=20, full_age=90)
    assert r.kick(s) is Due.FULL  # one full refresh covers the list too
    await r._task
    assert calls.kinds == ["full"]


async def test_failed_refresh_is_logged_not_raised(tmp_path, raw_models):
    r, calls, s = make(tmp_path, raw_models, list_age=20, full_age=30)

    def boom(_):
        raise httpx.ConnectError("offline")

    r.quick = boom
    r.kick(s)
    assert await r._task is False  # cache kept, bot keeps answering


async def test_slow_network_does_not_delay_store_get(tmp_path, raw_models):
    import time

    from loosechange.bot.store import DataStore

    r, calls, s = make(tmp_path, raw_models, list_age=20, full_age=30)

    def slow(_):
        time.sleep(0.5)

    r.quick = slow
    store = DataStore(path=tmp_path / "models.json", refresher=r)
    started = time.monotonic()
    snap = await store.get()
    assert time.monotonic() - started < 0.2
    assert snap is not None
    await r._task


async def test_store_uses_refresher(tmp_path, raw_models):
    from loosechange.bot.store import DataStore

    r, calls, s = make(tmp_path, raw_models, list_age=20, full_age=30)
    store = DataStore(path=tmp_path / "models.json", refresher=r)
    first = await store.get()  # served from cache, refresh started
    assert first.generated_at == s.generated_at
    await r._task
    second = await store.get()  # the next request sees the refreshed file
    assert calls.kinds == ["quick"]
    assert second.generated_at == T0
