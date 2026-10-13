"""Pure message renderers (Telegram HTML). Everything from OpenRouter is escaped."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from html import escape

from ..core.rank import (
    EXPIRING_FLAG,
    FALLBACK_FLAG,
    LOW_UPTIME_FLAG,
    NO_TOOLS_FLAG,
    RankResult,
    Scored,
)
from ..core.schema import History, Model, Snapshot
from ..integrations import Snippet
from .i18n import t

TG_LIMIT = 4096
PAGE_SIZE = 5
STALE_AFTER = timedelta(hours=12)


def fmt_ctx(n: int) -> str:
    if n >= 1_000_000:
        base = 1_000_000 if n % 1_000_000 == 0 else 1_048_576
        return f"{n / base:g}M"
    if n >= 1000:
        base = 1000 if n % 1000 == 0 else 1024
        return f"{n / base:g}k"
    return str(n)


def fmt_num(v: float | None) -> str:
    return "—" if v is None else f"{v:g}"


def profile_title(lang: str, key: str) -> str:
    return t(lang, f"p_{key}")


def priority_title(lang: str, key: str) -> str:
    return t(lang, f"pr_{key}")


def stale_footer(snapshot: Snapshot, lang: str, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    if now - snapshot.generated_at > STALE_AFTER:
        return t(lang, "stale", ts=snapshot.generated_at.strftime("%Y-%m-%d %H:%M UTC"))
    return ""


def time_left(lang: str, until: date, today: date | None = None) -> str:
    """Expiry countdown: «сегодня», «завтра», «через 18 дн.»."""
    days = (until - (today or date.today())).days
    if days < 0:
        return t(lang, "left_past")
    if days == 0:
        return t(lang, "left_today")
    if days == 1:
        return t(lang, "left_tomorrow")
    return t(lang, "left_days", n=days)


def ago(lang: str, then: datetime, now: datetime | None = None) -> str:
    minutes = max(0, int(((now or datetime.now(UTC)) - then).total_seconds() // 60))
    if minutes < 60:
        return t(lang, "ago_min", n=minutes)
    if minutes < 48 * 60:
        return t(lang, "ago_h", n=minutes // 60)
    return t(lang, "ago_d", n=minutes // 1440)


def model_lines(
    m: Model, lang: str, flags: list[str] | None = None, today: date | None = None
) -> list[str]:
    """Body of a card without the title line."""
    flags = flags or []
    b = m.benchmarks
    lines = [f"<code>{escape(m.id)}</code>"]
    stats = [f"🧠 {fmt_num(b.intelligence)}", f"💻 {fmt_num(b.coding)}", f"🤖 {fmt_num(b.agentic)}"]
    if b.design_elo is not None:
        stats.append(f"🎨 {b.design_elo:.0f}")
    stats.append(f"📏 {fmt_ctx(m.context_length)}")
    if m.tools:
        stats.append("🛠")
    if m.reasoning:
        stats.append("💭")
    lines.append(" · ".join(stats))
    warn = []
    up = m.reliability.uptime_30m if m.reliability else None
    if LOW_UPTIME_FLAG in flags and up is not None:
        warn.append(t(lang, "low_uptime", uptime=up))
    if m.expiration_date:
        key = "expires_soon" if EXPIRING_FLAG in flags else "expires"
        left = time_left(lang, m.expiration_date, today)
        warn.append(t(lang, key, date=m.expiration_date.isoformat(), left=left))
    if m.is_router:
        warn.append(t(lang, "router"))
    if NO_TOOLS_FLAG in flags:
        warn.append(t(lang, "no_tools"))
    if FALLBACK_FLAG in flags:
        warn.append(t(lang, "fallback_note"))
    if warn:
        lines.append(" · ".join(warn))
    return lines


def scored_card(s: Scored, lang: str) -> str:
    score = f"⭐ {s.score:g}" if s.rated else f"<i>{t(lang, 'unrated')}</i>"
    title = f"<b>{s.rank}. {escape(s.model.name)}</b> — {score}"
    return "\n".join([title, *model_lines(s.model, lang, s.flags)])


def model_card(m: Model, lang: str, today: date | None = None) -> str:
    from ..core.rank import expires_soon

    flags = [EXPIRING_FLAG] if expires_soon(m, today or date.today()) else []
    up = m.reliability.uptime_30m if m.reliability else None
    if up is not None and up < 90:
        flags.append(LOW_UPTIME_FLAG)
    parts = [f"<b>{escape(m.name)}</b>", *model_lines(m, lang, flags, today)]
    if m.description:
        parts.append(f"<i>{escape(m.description)}</i>")
    parts.append(f'<a href="{escape(m.url)}">openrouter.ai/{escape(m.id)}</a>')
    return "\n".join(parts)


def ranking_page(
    result: RankResult, lang: str, page: int = 0, page_size: int = PAGE_SIZE
) -> tuple[str, int]:
    """Text of one page of a ranking and the total number of pages."""
    items = result.all
    pages = max(1, -(-len(items) // page_size))
    page = min(max(page, 0), pages - 1)
    chunk = items[page * page_size : (page + 1) * page_size]
    head = t(
        lang,
        "top_header",
        profile=profile_title(lang, result.profile.key),
        priority=priority_title(lang, result.priority.value),
    )
    blocks = [head]
    if not items:
        blocks.append(t(lang, "no_models"))
    shown_unrated_header = False
    for s in chunk:
        if not s.rated and not shown_unrated_header:
            blocks.append(t(lang, "unrated_header"))
            shown_unrated_header = True
        blocks.append(scored_card(s, lang))
    if pages > 1:
        blocks.append(t(lang, "page", page=page + 1, pages=pages))
    return "\n\n".join(blocks), pages


def snippet_message(s: Snippet, model_id: str, lang: str) -> str:
    target = t(lang, f"t_{s.target}")
    parts = [
        t(lang, "snippet_header", target=target, id=escape(model_id)),
        f'<pre><code class="language-{s.language}">{escape(s.body)}</code></pre>',
    ]
    if s.command:
        parts.append(t(lang, "snippet_cli"))
        parts.append(f"<pre><code>{escape(s.command)}</code></pre>")
    notes = s.notes.get(lang) or s.notes.get("en") or []
    notes = [*notes, t(lang, "need_key")]
    parts.append("\n".join(f"• {escape(n)}" for n in notes))
    return "\n".join(parts)


def new_message(
    history: History, snapshot: Snapshot, lang: str, now: datetime | None = None
) -> str:
    now = now or datetime.now(UTC)
    since = now - timedelta(days=7)
    added: list[str] = []
    removed: list[str] = []
    for ev in history.events:
        if ev.ts < since:
            continue
        for i in ev.added:
            if i in removed:
                removed.remove(i)
            elif i not in added:
                added.append(i)
        for i in ev.removed:
            if i in added:
                added.remove(i)
            elif i not in removed:
                removed.append(i)

    def codes(ids: list[str]) -> str:
        return ", ".join(f"<code>{escape(i)}</code>" for i in ids)

    lines = [t(lang, "new_header")]
    if added:
        lines.append(t(lang, "new_added", ids=codes(added)))
    if removed:
        lines.append(t(lang, "new_removed", ids=codes(removed)))
    if not added and not removed:
        lines.append(t(lang, "new_none"))
    soon = [
        f"{m.id} — {time_left(lang, m.expiration_date, now.date())}"
        for m in sorted(snapshot.models, key=lambda m: m.expiration_date or date.max)
        if m.expiration_date and (m.expiration_date - now.date()).days <= 7
    ]
    if soon:
        lines.append(t(lang, "new_expiring", ids=codes(soon)))
    return "\n".join(lines)


def split_message(text: str, limit: int = TG_LIMIT) -> list[str]:
    """Split on blank lines / newlines so no chunk exceeds Telegram's limit."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    cur = ""
    for block in text.split("\n"):
        while len(block) > limit:  # pathological single line
            chunks.append(block[:limit])
            block = block[limit:]
        candidate = f"{cur}\n{block}" if cur else block
        if len(candidate) > limit:
            chunks.append(cur)
            cur = block
        else:
            cur = candidate
    if cur:
        chunks.append(cur)
    return chunks
