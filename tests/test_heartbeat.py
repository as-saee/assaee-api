from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.heartbeat import (
    ThreadState,
    effective_interval_hours,
    evaluate,
    select_nudges,
)

TZ = ZoneInfo("Europe/Madrid")
MON_NOON = datetime(2026, 10, 12, 10, 0, tzinfo=UTC)  # Monday 12:00 in Madrid (UTC+2)
CREATED = MON_NOON - timedelta(days=60)


def state(**kw) -> ThreadState:
    base = dict(id="t1", name="Book", kind="book", created_at=CREATED, touches=())
    base.update(kw)
    return ThreadState(**base)


def every(days: int, count: int, last: datetime) -> tuple[datetime, ...]:
    return tuple(last - timedelta(days=days * i) for i in range(count))


def test_default_rhythm_until_observed():
    assert effective_interval_hours(state(kind="book"), TZ) == 24
    assert effective_interval_hours(state(kind="gym"), TZ) == 72
    assert effective_interval_hours(state(kind="research"), TZ) == 168
    assert effective_interval_hours(state(kind="nonsense"), TZ) == 72


def test_learns_real_rhythm():
    touches = every(2, 7, MON_NOON - timedelta(days=1))  # 6 gaps of 2 days
    assert effective_interval_hours(state(kind="book", touches=touches), TZ) == 48


def test_few_touches_blend_with_default():
    touches = every(3, 2, MON_NOON - timedelta(days=1))  # 1 gap of 3 days = 72h; default is 24h
    interval = effective_interval_hours(state(kind="book", touches=touches), TZ)
    assert 24 < interval < 72


def test_many_touches_in_one_day_count_once():
    day = MON_NOON - timedelta(days=3)
    touches = tuple(day + timedelta(hours=h) for h in (0, 1, 2, 3)) + (
        MON_NOON - timedelta(days=2),
    )
    interval = effective_interval_hours(state(kind="book", touches=touches), TZ)
    assert interval >= 24  # a 1-day gap, never a 1-hour gap


def test_one_long_break_does_not_wreck_the_rhythm():
    last = MON_NOON - timedelta(days=1)
    touches = every(2, 6, last) + (last - timedelta(days=2 * 6 + 14),)  # a two-week break long ago
    assert effective_interval_hours(state(kind="book", touches=touches), TZ) == 48


def test_override_wins_and_can_be_cleared():
    touches = every(2, 7, MON_NOON - timedelta(days=1))
    assert effective_interval_hours(state(touches=touches, interval_override_hours=10), TZ) == 10
    assert effective_interval_hours(state(touches=touches, interval_override_hours=None), TZ) == 48


def test_quiet_only_after_one_and_a_half_times_the_usual_gap():
    touches = every(2, 7, MON_NOON - timedelta(hours=60))  # usual gap 48h; last touch 60h ago
    assert not evaluate(state(touches=touches), MON_NOON, TZ).quiet  # 1.25x
    touches = every(2, 7, MON_NOON - timedelta(hours=80))  # 1.67x
    s = evaluate(state(touches=touches), MON_NOON, TZ)
    assert s.quiet and s.nudgeable


def test_never_touched_counts_from_creation():
    s = evaluate(state(created_at=MON_NOON - timedelta(hours=10)), MON_NOON, TZ)
    assert s.last_touched is None and not s.quiet
    s = evaluate(state(created_at=MON_NOON - timedelta(days=5)), MON_NOON, TZ)
    assert s.quiet


def test_ignored_nudges_back_off():
    touches = every(1, 8, MON_NOON - timedelta(hours=40))  # usual 24h, now 1.67x
    assert evaluate(state(touches=touches), MON_NOON, TZ).quiet
    # two ignored nudges widen the threshold to 1.5 * 2.0 = 3x
    assert not evaluate(state(touches=touches, ignored_nudges=2), MON_NOON, TZ).quiet
    # backoff is capped, so a thread is never silenced forever
    far = every(1, 8, MON_NOON - timedelta(days=20))
    assert evaluate(state(touches=far, ignored_nudges=50), MON_NOON, TZ).quiet


def test_paused_and_snoozed_stay_quiet_but_do_not_nudge():
    old = (MON_NOON - timedelta(days=10),)
    paused = evaluate(state(touches=old, paused_until=MON_NOON + timedelta(days=2)), MON_NOON, TZ)
    assert paused.quiet and not paused.nudgeable
    snoozed = evaluate(
        state(touches=old, snoozed_until=MON_NOON + timedelta(hours=3)), MON_NOON, TZ
    )
    assert snoozed.quiet and not snoozed.nudgeable
    expired = evaluate(state(touches=old, paused_until=MON_NOON - timedelta(hours=1)), MON_NOON, TZ)
    assert expired.nudgeable


def test_only_nudges_on_active_days():
    old = (MON_NOON - timedelta(days=10),)
    workdays = frozenset(range(5))
    assert evaluate(state(touches=old, active_days=workdays), MON_NOON, TZ).nudgeable
    saturday = MON_NOON + timedelta(days=5)
    assert not evaluate(state(touches=old, active_days=workdays), saturday, TZ).nudgeable


def test_no_nudges_in_quiet_hours():
    old = (MON_NOON - timedelta(days=10),)
    night = datetime(2026, 10, 12, 21, 30, tzinfo=UTC)  # 23:30 in Madrid
    early = datetime(2026, 10, 12, 4, 0, tzinfo=UTC)  # 06:00 in Madrid
    assert not evaluate(state(touches=old), night, TZ).nudgeable
    assert not evaluate(state(touches=old), early, TZ).nudgeable
    assert evaluate(state(touches=old), MON_NOON, TZ).nudgeable


def test_selection_caps_and_ranks_most_overdue_first():
    def status(name: str, days_ago: int):
        return evaluate(
            state(id=name, name=name, touches=(MON_NOON - timedelta(days=days_ago),)), MON_NOON, TZ
        )

    statuses = [
        status("a", 3),
        status("b", 30),
        status("c", 10),
        status("d", 6),
        status("fresh", 0),
    ]
    chosen, rest = select_nudges(statuses, cap=2)
    assert [s.name for s in chosen] == ["b", "c"]
    assert sorted(s.name for s in rest) == ["a", "d"]
