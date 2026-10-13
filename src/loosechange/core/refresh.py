"""Timed refresh of the local snapshot (docs/ARCHITECTURE.md → «Обновление данных»).

Two expiry timers, both measured from timestamps stored in the snapshot itself,
so they survive restarts and a sleeping laptop:
- list TTL (default 15 min): after it expires the free-model list is re-fetched —
  one request to /models, ~1 s. Catches models that appear or disappear.
- full TTL (default 60 min): after it expires uptime is re-collected from
  /models/{id}/endpoints as well (~1 + N requests, 5–15 s).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from .collect import collect, quick_collect
from .schema import Snapshot

log = logging.getLogger(__name__)


class Due(StrEnum):
    NONE = "none"
    QUICK = "quick"  # list only
    FULL = "full"  # list + uptime


@dataclass(frozen=True)
class RefreshPolicy:
    list_ttl: timedelta = timedelta(minutes=15)
    full_ttl: timedelta = timedelta(minutes=60)

    @property
    def enabled(self) -> bool:
        return self.list_ttl > timedelta(0) or self.full_ttl > timedelta(0)

    @classmethod
    def from_minutes(cls, list_min: float, full_min: float) -> RefreshPolicy:
        return cls(timedelta(minutes=max(list_min, 0)), timedelta(minutes=max(full_min, 0)))


def due(snapshot: Snapshot | None, policy: RefreshPolicy, now: datetime) -> Due:
    """Which refresh the snapshot needs right now (pure function)."""
    if snapshot is None:
        return Due.FULL if policy.full_ttl else Due.QUICK
    if policy.full_ttl:
        last_full = snapshot.reliability_at
        if last_full is None or now - last_full >= policy.full_ttl:
            return Due.FULL
    if policy.list_ttl and now - snapshot.generated_at >= policy.list_ttl:
        return Due.QUICK
    return Due.NONE


def next_refresh_at(snapshot: Snapshot, policy: RefreshPolicy) -> datetime | None:
    times = []
    if policy.list_ttl:
        times.append(snapshot.generated_at + policy.list_ttl)
    if policy.full_ttl and snapshot.reliability_at:
        times.append(snapshot.reliability_at + policy.full_ttl)
    return min(times) if times else None


@dataclass
class Refresher:
    """Runs the collectors in a worker thread; never two at once."""

    data_dir: Path
    policy: RefreshPolicy = field(default_factory=RefreshPolicy)
    quick: Callable[[Path], object] = quick_collect
    full: Callable[[Path], object] = collect
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _full_task: asyncio.Task | None = None

    async def run(self, kind: Due) -> bool:
        if kind is Due.NONE:
            return False
        async with self._lock:
            try:
                fn = self.full if kind is Due.FULL else self.quick
                await asyncio.to_thread(fn, self.data_dir)
                log.info("data refreshed (%s)", kind.value)
                return True
            except Exception as exc:  # serve the last good snapshot
                log.warning("data refresh (%s) failed: %s", kind.value, exc)
                return False

    async def ensure_fresh(self, snapshot: Snapshot | None, timeout: float = 8.0) -> bool:
        """Called before answering a user. Returns True if the data on disk changed.

        Expired list -> refresh and wait for it (bounded by `timeout`, then answer from
        cache). Expired uptime only -> refresh in the background, answer right away."""
        kind = due(snapshot, self.policy, self.clock())
        if kind is Due.NONE:
            return False
        if kind is Due.FULL:
            task = self.start_full_in_background()
            if snapshot is not None and not self._list_expired(snapshot):
                return False
            awaitable = asyncio.shield(task)
        else:
            if self._lock.locked():
                return False
            awaitable = self.run(kind)
        try:
            return bool(await asyncio.wait_for(awaitable, timeout=timeout))
        except TimeoutError:
            log.warning("data refresh (%s) is slow; answering from cache", kind.value)
            return False

    def start_full_in_background(self) -> asyncio.Task:
        if self._full_task is None or self._full_task.done():
            self._full_task = asyncio.create_task(self.run(Due.FULL))
        return self._full_task

    def _list_expired(self, snapshot: Snapshot) -> bool:
        ttl = self.policy.list_ttl
        return bool(ttl) and self.clock() - snapshot.generated_at >= ttl

    async def loop(self, load: Callable[[], Snapshot | None], tick: float = 60.0) -> None:
        """Background timer: keeps data fresh even when nobody talks to the bot."""
        while True:
            await self.run(due(load(), self.policy, self.clock()))
            await asyncio.sleep(tick)
