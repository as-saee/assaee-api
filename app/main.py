from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import Base, engine
from app.routes import router


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)  # M1 only; schema migrations arrive with the Postgres move
    yield


app = FastAPI(title="As-Sa'ee API", version="0.1.0", lifespan=lifespan)
app.include_router(router)
