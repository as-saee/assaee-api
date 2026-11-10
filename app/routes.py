from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config, ntfy
from app.auth import require_key
from app.db import get_session
from app.heartbeat import Status, ThreadState, evaluate, select_nudges, snooze_until
from app.models import Thread, Touch
from app.schemas import (
    NudgeOut,
    NudgesOut,
    PauseRequest,
    SendOut,
    SnoozeRequest,
    ThreadCreate,
    ThreadOut,
    ThreadUpdate,
)

# /health stays open so uptime checks and k8s probes work without the key; the rest is locked.
public = APIRouter()
router = APIRouter(dependencies=[Depends(require_key)])


def get_now() -> datetime:
    return datetime.now(UTC)


def get_publisher() -> ntfy.Publisher:
    return ntfy.publish


def _days(thread: Thread) -> frozenset[int]:
    return frozenset(int(d) for d in thread.active_days.split(","))


def _state(thread: Thread) -> ThreadState:
    return ThreadState(
        id=thread.id,
        name=thread.name,
        kind=thread.kind,
        created_at=thread.created_at,
        touches=tuple(t.at for t in thread.touches),
        interval_override_hours=thread.interval_override_hours,
        active_days=_days(thread),
        paused_until=thread.paused_until,
        snoozed_until=thread.snoozed_until,
        ignored_nudges=thread.ignored_nudges,
    )


def _status(thread: Thread, now: datetime) -> Status:
    return evaluate(_state(thread), now, config.TZ, (config.QUIET_START, config.QUIET_END))


def _out(thread: Thread, now: datetime) -> ThreadOut:
    s = _status(thread, now)
    return ThreadOut(
        id=thread.id,
        name=thread.name,
        kind=thread.kind,
        last_touched=s.last_touched,
        interval_hours=s.interval_hours,
        elapsed_hours=s.elapsed_hours,
        overdue_ratio=s.overdue_ratio,
        quiet=s.quiet,
        nudgeable=s.nudgeable,
        paused_until=thread.paused_until,
        snoozed_until=thread.snoozed_until,
        active_days=sorted(_days(thread)),
    )


def _live_thread(session: Session, thread_id: str) -> Thread:
    thread = session.get(Thread, thread_id)
    if thread is None or thread.deleted_at is not None:
        raise HTTPException(404, "thread not found")
    return thread


def _ago(hours: float) -> str:
    if hours < 1:
        return "less than an hour ago"
    if hours < 48:
        n = round(hours)
        return f"{n} hour{'s' if n != 1 else ''} ago"
    n = round(hours / 24)
    return f"{n} days ago"


def _message(s: Status) -> str:
    if s.last_touched is None:
        when = f"added {_ago(s.elapsed_hours)}, not touched yet"
    else:
        when = f"last touched {_ago(s.elapsed_hours)}"
    return f"{s.name}: {when}"


@public.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/threads", response_model=ThreadOut, status_code=201)
def create_thread(
    body: ThreadCreate, session: Session = Depends(get_session), now: datetime = Depends(get_now)
):
    thread = Thread(
        name=body.name,
        kind=body.kind,
        interval_override_hours=body.interval_hours,
        active_days=",".join(map(str, body.active_days)) if body.active_days else "0,1,2,3,4,5,6",
        created_at=now,
        updated_at=now,
    )
    session.add(thread)
    session.commit()
    return _out(thread, now)


@router.get("/threads", response_model=list[ThreadOut])
def list_threads(session: Session = Depends(get_session), now: datetime = Depends(get_now)):
    threads = session.scalars(
        select(Thread).where(Thread.deleted_at.is_(None)).order_by(Thread.created_at)
    ).all()
    return [_out(t, now) for t in threads]


@router.patch("/threads/{thread_id}", response_model=ThreadOut)
def update_thread(
    thread_id: str,
    body: ThreadUpdate,
    session: Session = Depends(get_session),
    now: datetime = Depends(get_now),
):
    thread = _live_thread(session, thread_id)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is not None:
        thread.name = changes["name"]
    if "kind" in changes and changes["kind"] is not None:
        thread.kind = changes["kind"]
    if "interval_hours" in changes:
        thread.interval_override_hours = changes["interval_hours"]  # None returns to learned rhythm
    if "active_days" in changes and changes["active_days"] is not None:
        thread.active_days = ",".join(map(str, changes["active_days"]))
    thread.updated_at = now
    session.commit()
    return _out(thread, now)


@router.delete("/threads/{thread_id}", status_code=204)
def delete_thread(
    thread_id: str, session: Session = Depends(get_session), now: datetime = Depends(get_now)
):
    thread = _live_thread(session, thread_id)
    thread.deleted_at = now
    thread.updated_at = now
    session.commit()
    return Response(status_code=204)


@router.post("/threads/{thread_id}/touch", response_model=ThreadOut)
def touch_thread(
    thread_id: str, session: Session = Depends(get_session), now: datetime = Depends(get_now)
):
    thread = _live_thread(session, thread_id)
    session.add(Touch(thread_id=thread.id, at=now))
    thread.ignored_nudges = 0
    thread.snoozed_until = None
    thread.updated_at = now
    session.commit()
    session.refresh(thread)
    return _out(thread, now)


@router.post("/threads/{thread_id}/snooze", response_model=ThreadOut)
def snooze_thread(
    thread_id: str,
    body: SnoozeRequest,
    session: Session = Depends(get_session),
    now: datetime = Depends(get_now),
):
    thread = _live_thread(session, thread_id)
    thread.snoozed_until = snooze_until(now, body.hours)
    thread.ignored_nudges += 1  # repeated snoozes make this thread back off
    thread.updated_at = now
    session.commit()
    return _out(thread, now)


@router.post("/threads/{thread_id}/pause", response_model=ThreadOut)
def pause_thread(
    thread_id: str,
    body: PauseRequest,
    session: Session = Depends(get_session),
    now: datetime = Depends(get_now),
):
    if body.until.tzinfo is None:
        raise HTTPException(422, "until must include a timezone offset")
    thread = _live_thread(session, thread_id)
    thread.paused_until = body.until
    thread.updated_at = now
    session.commit()
    return _out(thread, now)


@router.post("/threads/{thread_id}/resume", response_model=ThreadOut)
def resume_thread(
    thread_id: str, session: Session = Depends(get_session), now: datetime = Depends(get_now)
):
    thread = _live_thread(session, thread_id)
    thread.paused_until = None
    thread.snoozed_until = None
    thread.updated_at = now
    session.commit()
    return _out(thread, now)


def _build_nudges(session: Session, now: datetime) -> NudgesOut:
    threads = session.scalars(select(Thread).where(Thread.deleted_at.is_(None))).all()
    chosen, rest = select_nudges([_status(t, now) for t in threads], config.NUDGE_CAP)
    items = [
        NudgeOut(
            id=s.thread_id,
            name=s.name,
            kind=s.kind,
            elapsed_hours=s.elapsed_hours,
            interval_hours=s.interval_hours,
            message=_message(s),
        )
        for s in chosen
    ]
    summary = None
    if rest:
        summary = f"{len(rest)} more have gone quiet: " + ", ".join(s.name for s in rest)
    return NudgesOut(nudges=items, grouped=len(rest), summary=summary)


@router.get("/nudges", response_model=NudgesOut)
def nudges(session: Session = Depends(get_session), now: datetime = Depends(get_now)):
    return _build_nudges(session, now)


@router.post("/nudges/send", response_model=SendOut)
def send_nudges(
    session: Session = Depends(get_session),
    now: datetime = Depends(get_now),
    publisher: ntfy.Publisher = Depends(get_publisher),
):
    if not config.NTFY_URL:
        raise HTTPException(503, "nudge delivery is off: ASSAEE_NTFY_URL is not set")
    due = _build_nudges(session, now)
    messages = [(n.name, n.message) for n in due.nudges]
    if due.summary:
        messages.append(("More have gone quiet", due.summary))
    try:
        for title, message in messages:
            publisher(title, message)
    except ntfy.NtfyError as exc:
        raise HTTPException(502, f"could not reach ntfy: {exc}") from exc
    return SendOut(sent=len(messages))
