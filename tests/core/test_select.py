from datetime import date

from loosechange.core.collect import build_snapshot
from loosechange.core.schema import Reliability
from loosechange.core.select import choose

TODAY = date(2026, 10, 14)


def snap_with_access(raw_models):
    s = build_snapshot(raw_models)
    for m in s.models:
        if m.id.startswith("thinkingmachines/inkling"):
            m.access = "harness_only"
        elif m.id.startswith("nvidia/"):
            m.access = "open"
        if m.id == "nvidia/nemotron-3-ultra-550b-a55b:free":
            m.reliability = Reliability(uptime_30m=60.0)  # flaky right now
    return s


def test_picks_skip_harness_only_router_and_flaky(raw_models):
    s = snap_with_access(raw_models)
    sel = choose(s, "nvidia/nemotron-3-super-120b-a12b:free", top=3, today=TODAY)
    ids = [m.id for m in sel.picks]
    assert len(ids) == 3
    assert not any(i.startswith("thinkingmachines/") or i.startswith("openrouter/") for i in ids)
    assert "nvidia/nemotron-3-ultra-550b-a55b:free" not in ids  # flaky: skipped
    opens = [s.get(i).access == "open" for i in ids]
    assert opens == sorted(opens, reverse=True)  # verified-open first
    assert sel.new_default is None  # a working default stays


def test_default_replaced_only_when_broken(raw_models):
    s = snap_with_access(raw_models)
    for current, why in [
        (None, "no default"),
        ("vendor/gone:free", "no longer a free model"),
        ("thinkingmachines/inkling:free", "harness-only"),
    ]:
        sel = choose(s, current, today=TODAY)
        assert sel.new_default == sel.picks[0].id
        assert why in sel.reasons[0]


def test_congested_skipped_and_default_replaced(raw_models):
    from datetime import UTC, datetime

    s = snap_with_access(raw_models)
    s.get("nvidia/nemotron-3-super-120b-a12b:free").congested_at = datetime.now(UTC)
    sel = choose(s, "nvidia/nemotron-3-super-120b-a12b:free", top=3, today=TODAY)
    assert "nvidia/nemotron-3-super-120b-a12b:free" not in [m.id for m in sel.picks]
    assert sel.new_default and "rate-limited" in sel.reasons[0]


def test_harness_mode_allows_harness_only_first(raw_models):
    s = snap_with_access(raw_models)
    sel = choose(s, None, top=2, today=TODAY, harness=True)
    assert sel.picks[0].id.startswith("thinkingmachines/inkling")
