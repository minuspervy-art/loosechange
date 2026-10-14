"""Snapshot source for the bot: local file (mtime-watched) or a URL (raw GitHub)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from ..core.collect import load_history, load_snapshot
from ..core.refresh import Refresher
from ..core.schema import History, Snapshot

log = logging.getLogger(__name__)


@dataclass
class DataStore:
    path: Path | None = None  # data/models.json
    # e.g. https://raw.githubusercontent.com/minuspervy-art/loosechange/main/data/models.json
    url: str | None = None
    refresh_s: int = 600
    refresher: Refresher | None = None  # timed refresh of the local file (path mode)
    snapshot: Snapshot | None = None
    history: History = field(default_factory=History)
    _mtime: int = 0
    _fetched: float = 0.0

    async def get(self) -> Snapshot | None:
        try:
            if self.url:
                await self._refresh_url()
            elif self.path:
                self._refresh_file()  # picks up whatever a finished refresh wrote
                if self.refresher:
                    self.refresher.kick(self.snapshot)  # non-blocking
        except Exception as exc:  # keep serving the last good snapshot
            log.warning("snapshot refresh failed: %s", exc)
        return self.snapshot

    def _refresh_file(self) -> None:
        assert self.path is not None
        if not self.path.exists():
            return
        mtime = self.path.stat().st_mtime_ns
        if mtime == self._mtime and self.snapshot:
            return
        snap = load_snapshot(self.path)
        if snap:
            self.snapshot = snap
            self.history = load_history(self.path.parent / "history" / "changes.json")
            self._mtime = mtime

    async def _refresh_url(self) -> None:
        assert self.url is not None
        if self.snapshot and time.monotonic() - self._fetched < self.refresh_s:
            return
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(self.url)
            r.raise_for_status()
            self.snapshot = Snapshot.model_validate_json(r.content)
            hist_url = self.url.rsplit("/", 1)[0] + "/history/changes.json"
            h = await client.get(hist_url)
            if h.status_code == 200:
                self.history = History.model_validate_json(h.content)
        self._fetched = time.monotonic()
