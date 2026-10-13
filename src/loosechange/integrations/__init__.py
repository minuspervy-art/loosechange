"""Adapters that add a model to local tools: Hermes, VibeForge, generic."""

from __future__ import annotations

from . import hermes, vibeforge
from .base import ApplyNotSupported, Snippet, alias_for, render_generic

TARGETS = ("hermes", "vibeforge", "other")


def render(target: str, model_id: str, profile: str) -> Snippet:
    if target == "hermes":
        return hermes.render(model_id, profile)
    if target == "vibeforge":
        return vibeforge.render(model_id, profile)
    if target == "other":
        return render_generic(model_id, profile)
    raise ValueError(f"unknown target {target!r}; choose from {', '.join(TARGETS)}")


__all__ = ["TARGETS", "ApplyNotSupported", "Snippet", "alias_for", "render"]
