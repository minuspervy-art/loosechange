"""Pydantic schema of the public snapshot `data/models.json`."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1


class DesignArenaEntry(BaseModel):
    arena: str
    category: str
    elo: float | None = None
    win_rate: float | None = None
    rank: int | None = None


class Benchmarks(BaseModel):
    """Benchmarks exactly as OpenRouter reports them (never invented)."""

    intelligence: float | None = None
    coding: float | None = None
    agentic: float | None = None
    design_arena: list[DesignArenaEntry] = Field(default_factory=list)

    @property
    def design_elo(self) -> float | None:
        """Mean Elo over the `models` arena categories (comparable across models)."""
        elos = [e.elo for e in self.design_arena if e.arena == "models" and e.elo is not None]
        return sum(elos) / len(elos) if elos else None

    @property
    def has_any(self) -> bool:
        return any(
            v is not None for v in (self.intelligence, self.coding, self.agentic, self.design_elo)
        )


class Reliability(BaseModel):
    """Best-provider stats from `/models/{id}/endpoints` (None = not published)."""

    uptime_30m: float | None = None
    uptime_1d: float | None = None
    latency_30m: float | None = None
    throughput_30m: float | None = None
    providers: int = 0


class Model(BaseModel):
    id: str
    name: str
    description: str = ""
    context_length: int = 0
    max_completion_tokens: int | None = None
    input_modalities: list[str] = Field(default_factory=list)
    output_modalities: list[str] = Field(default_factory=list)
    supported_parameters: list[str] = Field(default_factory=list)
    created: int | None = None
    expiration_date: date | None = None
    knowledge_cutoff: str | None = None
    is_free_variant: bool = False  # `:free` suffix -> strict shared rate limits
    is_router: bool = False  # e.g. openrouter/free picks a random free model
    benchmarks: Benchmarks = Field(default_factory=Benchmarks)
    reliability: Reliability | None = None
    first_seen: datetime | None = None

    @property
    def tools(self) -> bool:
        return "tools" in self.supported_parameters

    @property
    def reasoning(self) -> bool:
        return "reasoning" in self.supported_parameters

    @property
    def url(self) -> str:
        return f"https://openrouter.ai/{self.id}"


class Excluded(BaseModel):
    id: str
    reason: str


class Snapshot(BaseModel):
    schema_version: int = SCHEMA_VERSION
    generated_at: datetime  # when the model list was fetched
    reliability_at: datetime | None = None  # when uptime (/endpoints) was last fetched
    source: str = "https://openrouter.ai/api/v1/models"
    total_models: int = 0
    models: list[Model] = Field(default_factory=list)
    excluded: list[Excluded] = Field(default_factory=list)

    def get(self, model_id: str) -> Model | None:
        return next((m for m in self.models if m.id == model_id), None)


class HistoryEvent(BaseModel):
    ts: datetime
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)


class History(BaseModel):
    events: list[HistoryEvent] = Field(default_factory=list)
