from datetime import date

import pytest

from loosechange.collect import build_snapshot
from loosechange.models import Benchmarks, DesignArenaEntry, Model, Reliability
from loosechange.profiles import PROFILES, Priority, get_profile
from loosechange.rank import (
    EXPIRING_FLAG,
    FALLBACK_FLAG,
    LOW_UPTIME_FLAG,
    NO_TOOLS_FLAG,
    normalize_log_ctx,
    normalize_max,
    rank,
)

TODAY = date(2026, 10, 13)
TOOLS = ["max_tokens", "tools"]
REASON = ["reasoning", "tools"]


def mk(id, i=None, c=None, a=None, ctx=262_144, params=TOOLS, uptime=100.0, tput=None, **kw):
    return Model(
        id=id,
        name=id,
        context_length=ctx,
        supported_parameters=params,
        benchmarks=Benchmarks(intelligence=i, coding=c, agentic=a, **kw.pop("bench", {})),
        reliability=Reliability(uptime_30m=uptime, throughput_30m=tput),
        **kw,
    )


def ids(models):
    return [s.model.id for s in models]


def test_normalize_max():
    assert normalize_max({"a": 50, "b": 100, "c": None}) == {"a": 50, "b": 100, "c": None}
    assert normalize_max({"a": None}) == {"a": None}


def test_normalize_log_ctx_floor():
    import math

    out = normalize_log_ctx({"a": math.log(256_000), "b": math.log(1_024_000)}, 256_000)
    assert out["a"] == pytest.approx(0)
    assert out["b"] == pytest.approx(100)


def test_agent_profile_weights_and_requirements():
    models = [
        mk("strong", i=20, c=50, a=20),
        mk("weak", i=10, c=25, a=10),
        mk("no-tools", i=90, c=90, a=90, params=["max_tokens"]),
        mk("small-ctx", i=90, c=90, a=90, ctx=64_000),
        mk("no-agentic", i=5, c=10),  # candidate, but lacks the primary index
    ]
    r = rank(models, get_profile("agent"), today=TODAY)
    assert ids(r.rated) == ["strong", "weak"]
    assert r.rated[0].score == 100.0
    assert r.rated[1].score == pytest.approx(50.0)
    assert ids(r.unrated) == ["no-agentic"]  # primary index missing -> unrated, not zero
    assert "no-tools" not in ids(r.all) and "small-ctx" not in ids(r.all)
    assert [s.rank for s in r.all] == [1, 2, 3]


def test_null_component_weight_is_redistributed():
    # coding missing -> score from agentic+intelligence only (0.5 and 0.2 renormalized)
    models = [mk("full", i=20, c=50, a=20), mk("partial", i=20, a=20)]
    r = rank(models, get_profile("agent"), today=TODAY)
    partial = next(s for s in r.rated if s.model.id == "partial")
    assert partial.score == 100.0


def test_coding_profile_prefers_tools():
    models = [mk("tools", i=10, c=50), mk("plain", i=10, c=50, params=["max_tokens"])]
    r = rank(models, get_profile("coding"), today=TODAY)
    assert ids(r.rated) == ["tools", "plain"]
    assert NO_TOOLS_FLAG in r.rated[1].flags
    assert r.rated[0].score - r.rated[1].score == pytest.approx(5.0)


def test_chat_profile_intelligence_only():
    r = rank([mk("a", i=10), mk("b", i=40), mk("x")], get_profile("chat"), today=TODAY)
    assert ids(r.rated) == ["b", "a"]
    assert ids(r.unrated) == ["x"]


def test_reasoning_requires_reasoning_param():
    models = [mk("thinks", i=10, c=10, params=REASON), mk("fast", i=50, c=50)]
    r = rank(models, get_profile("reasoning"), today=TODAY)
    assert ids(r.all) == ["thinks"]


def test_longctx_requires_256k_and_rewards_context():
    models = [
        mk("huge", i=20, ctx=1_048_576),
        mk("base", i=20, ctx=262_144),
        mk("short", i=50, ctx=128_000),
    ]
    r = rank(models, get_profile("longctx"), today=TODAY)
    assert ids(r.rated) == ["huge", "base"]
    assert r.rated[0].score > r.rated[1].score


def test_fast_cheap_unavailable_without_speed_data():
    r = rank([mk("a", i=10), mk("b", i=20)], get_profile("fast_cheap"), today=TODAY)
    assert not r.available and r.reason == "no_speed_data"
    assert r.all == []


def test_fast_cheap_uses_throughput_when_published():
    models = [mk("slow-smart", i=40, tput=20), mk("fast", i=20, tput=200)]
    r = rank(models, get_profile("fast_cheap"), today=TODAY)
    assert r.available
    assert ids(r.rated) == ["fast", "slow-smart"]


def test_design_uses_arena_then_coding_fallback():
    arena = [DesignArenaEntry(arena="models", category="website", elo=1200)]
    weak_arena = [DesignArenaEntry(arena="models", category="website", elo=1100)]
    models = [
        mk("coder", c=99),
        mk("designer", bench={"design_arena": arena}),
        mk("designer2", bench={"design_arena": weak_arena}),
        mk("nothing"),
    ]
    r = rank(models, get_profile("design"), today=TODAY)
    assert ids(r.rated) == ["designer", "designer2", "coder"]
    assert FALLBACK_FLAG in r.rated[-1].flags
    assert ids(r.unrated) == ["nothing"]


def test_low_uptime_penalty():
    models = [mk("flaky", i=40, uptime=50), mk("solid", i=38)]
    r = rank(models, get_profile("chat"), today=TODAY)
    assert ids(r.rated) == ["solid", "flaky"]
    assert LOW_UPTIME_FLAG in r.rated[1].flags
    assert r.rated[1].score == pytest.approx(90.0)


def test_priority_stability_and_context():
    models = [mk("a", i=40, uptime=95, ctx=262_144), mk("b", i=39, uptime=None, ctx=1_048_576)]
    models[1].reliability = None
    q = rank(models, get_profile("chat"), Priority.QUALITY, today=TODAY)
    assert ids(q.rated) == ["a", "b"]
    s = rank(models, get_profile("chat"), "stability", today=TODAY)
    assert ids(s.rated) == ["a", "b"]
    assert s.rated[1].score < q.rated[1].score
    c = rank(models, get_profile("chat"), Priority.CONTEXT, today=TODAY)
    assert ids(c.rated) == ["b", "a"]


def test_expiring_flag():
    m = mk("old", i=10, expiration_date=date(2026, 10, 18))
    r = rank([m], get_profile("chat"), today=TODAY)
    assert EXPIRING_FLAG in r.rated[0].flags
    r2 = rank([m], get_profile("chat"), today=date(2026, 9, 1))
    assert EXPIRING_FLAG not in r2.rated[0].flags


@pytest.mark.parametrize("key", list(PROFILES))
def test_every_profile_on_real_fixture(raw_models, key):
    snap = build_snapshot(raw_models)
    r = rank(snap.models, get_profile(key), today=TODAY)
    for s in r.rated:
        assert 0 <= s.score <= 100
    for s in r.unrated:
        assert s.score is None
        assert s.model.benchmarks.has_any is False or s.components[get_profile(key).primary] is None
    # models without any benchmark can never be rated
    assert all(s.model.benchmarks.has_any for s in r.rated)
    if key != "fast_cheap":
        assert r.available and r.rated


def test_unknown_profile():
    with pytest.raises(ValueError):
        get_profile("nope")
