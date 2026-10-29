from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime
from app.ids import uuid7


class Thread(Base):
    __tablename__ = "threads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="other")
    interval_override_hours: Mapped[float | None] = mapped_column(default=None)
    active_days: Mapped[str] = mapped_column(String(13), default="0,1,2,3,4,5,6")
    paused_until: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    snoozed_until: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    ignored_nudges: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)

    touches: Mapped[list["Touch"]] = relationship(back_populates="thread", order_by="Touch.at")


class Touch(Base):
    __tablename__ = "touches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    thread_id: Mapped[str] = mapped_column(ForeignKey("threads.id"), index=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime)

    thread: Mapped[Thread] = relationship(back_populates="touches")
