from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.heartbeat import KINDS


def _check_days(days: list[int]) -> list[int]:
    if not days or any(d < 0 or d > 6 for d in days):
        raise ValueError("active_days must be a non-empty list of weekdays 0 (Mon) to 6 (Sun)")
    return sorted(set(days))


class ThreadCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str = "other"
    interval_hours: float | None = Field(default=None, gt=0)
    active_days: list[int] | None = None

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        return v

    @field_validator("active_days")
    @classmethod
    def _days(cls, v):
        return None if v is None else _check_days(v)


class ThreadUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: str | None = None
    interval_hours: float | None = Field(default=None, gt=0)
    active_days: list[int] | None = None

    @field_validator("kind")
    @classmethod
    def _kind(cls, v):
        if v is not None and v not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        return v

    @field_validator("active_days")
    @classmethod
    def _days(cls, v):
        return None if v is None else _check_days(v)


class SnoozeRequest(BaseModel):
    hours: float = Field(gt=0, le=24 * 30)


class PauseRequest(BaseModel):
    until: datetime


class ThreadOut(BaseModel):
    id: str
    name: str
    kind: str
    last_touched: datetime | None
    interval_hours: float
    elapsed_hours: float
    overdue_ratio: float
    quiet: bool
    nudgeable: bool
    paused_until: datetime | None
    snoozed_until: datetime | None
    active_days: list[int]


class NudgeOut(BaseModel):
    id: str
    name: str
    kind: str
    elapsed_hours: float
    interval_hours: float
    message: str


class NudgesOut(BaseModel):
    nudges: list[NudgeOut]
    grouped: int
    summary: str | None
