"""Heartbeat logic: when has a thread gone quiet, and which quiet threads are worth a nudge today.

Pure functions, no I/O, so the rules can be tested without a database or a clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo

# Starting rhythm per kind of thread, used until the real rhythm has been observed.
DEFAULT_INTERVAL_HOURS = {
    "book": 24.0,
    "project": 24.0,
    "gym": 72.0,
    "research": 168.0,
    "inbox": 168.0,
    "other": 72.0,
}
KINDS = tuple(DEFAULT_INTERVAL_HOURS)

QUIET_FACTOR = 1.5  # a thread is quiet once the gap is this many times its usual gap
GAPS_USED = 8  # most recent gaps that define "usual"
GAPS_FOR_FULL_TRUST = 5  # until this many gaps exist, blend with the default rhythm
BACKOFF_STEP = 0.5  # each ignored nudge widens the quiet threshold by this much
BACKOFF_MAX = 3.0


@dataclass(frozen=True)
class ThreadState:
    id: str
    name: str
    kind: str
    created_at: datetime
    touches: tuple[datetime, ...]
    interval_override_hours: float | None = None
    active_days: frozenset[int] = frozenset(range(7))  # Monday=0 .. Sunday=6, local time
    paused_until: datetime | None = None
    snoozed_until: datetime | None = None
    ignored_nudges: int = 0


@dataclass(frozen=True)
class Status:
    thread_id: str
    name: str
    kind: str
    last_touched: datetime | None
    interval_hours: float
    elapsed_hours: float
    overdue_ratio: float  # elapsed / usual interval; 1.0 means "right on rhythm"
    quiet: bool
    nudgeable: bool  # quiet, and allowed to interrupt right now


def effective_interval_hours(state: ThreadState, tz: ZoneInfo) -> float:
    """The user's override if set, else the observed rhythm blended with the default for the kind.

    Rhythm is measured between distinct local days, so touching a thread three times in one day
    counts as one touch and cannot shrink the interval.
    """
    if state.interval_override_hours:
        return state.interval_override_hours
    default = DEFAULT_INTERVAL_HOURS.get(state.kind, DEFAULT_INTERVAL_HOURS["other"])
    days = sorted({t.astimezone(tz).date() for t in state.touches})
    gaps = [(b - a).days * 24.0 for a, b in zip(days, days[1:], strict=False)][-GAPS_USED:]
    if not gaps:
        return default
    trust = min(1.0, len(gaps) / GAPS_FOR_FULL_TRUST)
    return trust * median(gaps) + (1 - trust) * default


def _in_quiet_hours(local_hour: int, start: int, end: int) -> bool:
    if start == end:
        return False
    if start < end:
        return start <= local_hour < end
    return local_hour >= start or local_hour < end


def evaluate(
    state: ThreadState,
    now: datetime,
    tz: ZoneInfo,
    quiet_hours: tuple[int, int] = (22, 7),
) -> Status:
    interval = effective_interval_hours(state, tz)
    last = max(state.touches) if state.touches else None
    since = last or state.created_at
    elapsed = max(0.0, (now - since).total_seconds() / 3600)
    ratio = elapsed / interval
    backoff = min(BACKOFF_MAX, 1 + BACKOFF_STEP * state.ignored_nudges)
    quiet = ratio >= QUIET_FACTOR * backoff

    local = now.astimezone(tz)
    allowed = (
        (state.paused_until is None or state.paused_until <= now)
        and (state.snoozed_until is None or state.snoozed_until <= now)
        and local.weekday() in state.active_days
        and not _in_quiet_hours(local.hour, *quiet_hours)
    )
    return Status(
        thread_id=state.id,
        name=state.name,
        kind=state.kind,
        last_touched=last,
        interval_hours=round(interval, 2),
        elapsed_hours=round(elapsed, 2),
        overdue_ratio=round(ratio, 2),
        quiet=quiet,
        nudgeable=quiet and allowed,
    )


def select_nudges(statuses: list[Status], cap: int) -> tuple[list[Status], list[Status]]:
    """Most overdue first, at most `cap` individual nudges; the rest are grouped in one summary."""
    ranked = sorted(
        (s for s in statuses if s.nudgeable), key=lambda s: s.overdue_ratio, reverse=True
    )
    return ranked[:cap], ranked[cap:]


def snooze_until(now: datetime, hours: float) -> datetime:
    return now + timedelta(hours=hours)
