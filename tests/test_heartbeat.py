from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

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


# ---- edges: the exact boundaries of each rule -------------------------------------------------


def _old_thread_at(now: datetime) -> ThreadState:
    return state(touches=(now - timedelta(days=10),))


@pytest.mark.parametrize(
    ("utc_time", "nudgeable"),
    [
        ((19, 59), True),  # 21:59 in Madrid: still allowed
        ((20, 0), False),  # 22:00: quiet hours start (inclusive)
        ((4, 59), False),  # 06:59: still quiet
        ((5, 0), True),  # 07:00: quiet hours end (exclusive)
    ],
)
def test_quiet_hours_boundaries(utc_time, nudgeable):
    now = datetime(2026, 10, 12, *utc_time, tzinfo=UTC)
    assert evaluate(_old_thread_at(now), now, TZ).nudgeable is nudgeable


def test_quiet_hours_with_equal_start_and_end_means_never_quiet():
    night = datetime(2026, 10, 12, 21, 30, tzinfo=UTC)  # 23:30 in Madrid
    assert evaluate(_old_thread_at(night), night, TZ, quiet_hours=(5, 5)).nudgeable


def test_quiet_hours_window_that_does_not_wrap_midnight():
    thread = _old_thread_at(MON_NOON)
    three_am = datetime(2026, 10, 12, 1, 0, tzinfo=UTC)  # 03:00 in Madrid, inside 01-05
    five_am = datetime(2026, 10, 12, 3, 0, tzinfo=UTC)  # 05:00 in Madrid, window is exclusive
    one_am = datetime(2026, 10, 11, 23, 0, tzinfo=UTC)  # 01:00 in Madrid, window is inclusive
    midnight = datetime(2026, 10, 11, 22, 59, tzinfo=UTC)  # 00:59 in Madrid, just before it
    assert not evaluate(thread, one_am, TZ, quiet_hours=(1, 5)).nudgeable
    assert evaluate(thread, midnight, TZ, quiet_hours=(1, 5)).nudgeable
    assert not evaluate(thread, three_am, TZ, quiet_hours=(1, 5)).nudgeable
    assert evaluate(thread, five_am, TZ, quiet_hours=(1, 5)).nudgeable


def test_quiet_starts_at_exactly_one_and_a_half_times_the_usual_gap():
    def quiet_after(hours: float) -> bool:
        touches = every(1, 8, MON_NOON - timedelta(hours=hours))  # usual gap: 24h
        return evaluate(state(touches=touches), MON_NOON, TZ).quiet

    assert not quiet_after(35.9)
    assert quiet_after(36)


def test_snooze_and_pause_that_end_exactly_now_are_over():
    old = (MON_NOON - timedelta(days=10),)
    assert evaluate(state(touches=old, snoozed_until=MON_NOON), MON_NOON, TZ).nudgeable
    assert evaluate(state(touches=old, paused_until=MON_NOON), MON_NOON, TZ).nudgeable
    later = MON_NOON + timedelta(seconds=1)
    assert not evaluate(state(touches=old, snoozed_until=later), MON_NOON, TZ).nudgeable
    assert not evaluate(state(touches=old, paused_until=later), MON_NOON, TZ).nudgeable


@pytest.mark.parametrize(
    ("ignored", "threshold_hours"),
    [(0, 36), (1, 54), (2, 72), (3, 90), (4, 108), (5, 108), (50, 108)],  # 24h * 1.5 * (1 + n/2)
)
def test_backoff_steps_and_cap(ignored, threshold_hours):
    def quiet_after(hours: float) -> bool:
        touches = every(1, 8, MON_NOON - timedelta(hours=hours))
        return evaluate(state(touches=touches, ignored_nudges=ignored), MON_NOON, TZ).quiet

    assert not quiet_after(threshold_hours - 1)
    assert quiet_after(threshold_hours)


def test_only_the_eight_most_recent_gaps_define_the_rhythm():
    last = MON_NOON - timedelta(days=1)
    recent = every(2, 9, last)  # 8 gaps of 2 days
    older = tuple(recent[-1] - timedelta(days=k) for k in range(1, 11))  # 10 gaps of 1 day
    assert effective_interval_hours(state(touches=recent + older), TZ) == 48


def test_full_trust_needs_five_gaps():
    last = MON_NOON - timedelta(days=1)
    four = every(2, 5, last)  # 4 gaps of 48h, book default 24h: 0.8 * 48 + 0.2 * 24
    five = every(2, 6, last)
    assert effective_interval_hours(state(touches=four), TZ) == pytest.approx(43.2)
    assert effective_interval_hours(state(touches=five), TZ) == 48


def test_days_are_local_days_not_utc_days():
    gym = {"kind": "gym"}  # default 72h; one 24h gap gives 0.2 * 24 + 0.8 * 72 = 62.4
    # 23:30 and 00:30 Madrid time: one hour apart but on adjacent local days
    adjacent = (
        datetime(2026, 10, 12, 21, 30, tzinfo=UTC),
        datetime(2026, 10, 12, 22, 30, tzinfo=UTC),
    )
    assert effective_interval_hours(state(touches=adjacent, **gym), TZ) == pytest.approx(62.4)
    # 00:30 and 23:30 Madrid time: different UTC days but the same local day, so no gap at all
    same_day = (
        datetime(2026, 10, 11, 22, 30, tzinfo=UTC),
        datetime(2026, 10, 12, 21, 30, tzinfo=UTC),
    )
    assert effective_interval_hours(state(touches=same_day, **gym), TZ) == 72


def test_clock_change_does_not_stretch_a_two_day_gap():
    # Madrid clocks go back on 2026-10-25, so noon to noon across it is 49 real hours.
    touches = (datetime(2026, 10, 24, 12, 0, tzinfo=TZ), datetime(2026, 10, 26, 12, 0, tzinfo=TZ))
    interval = effective_interval_hours(state(kind="gym", touches=touches), TZ)
    assert interval == pytest.approx(0.2 * 48 + 0.8 * 72)  # two local days = 48h, not 49h


def test_selection_edges():
    def status(name: str, days_ago: int, **kw):
        touches = (MON_NOON - timedelta(days=days_ago),)
        return evaluate(state(id=name, name=name, touches=touches, **kw), MON_NOON, TZ)

    paused = status("paused", 30, paused_until=MON_NOON + timedelta(days=1))
    a, b = status("a", 10), status("b", 10)  # a tie
    chosen, rest = select_nudges([paused, a, b], cap=0)
    assert chosen == [] and [s.name for s in rest] == ["a", "b"]  # paused is in neither list
    chosen, rest = select_nudges([paused, a, b], cap=5)
    assert [s.name for s in chosen] == ["a", "b"] and rest == []  # a tie keeps input order
