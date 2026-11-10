from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import config
from app.db import Base, engine
from app.routes import public, router


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not config.API_KEY:
        raise RuntimeError("ASSAEE_API_KEY is not set; refusing to start without authentication")
    Base.metadata.create_all(engine)  # M1 only; schema migrations arrive with the Postgres move
    yield


app = FastAPI(title="As-Sa'ee API", version="0.1.0", lifespan=lifespan)
app.include_router(public)
app.include_router(router)
