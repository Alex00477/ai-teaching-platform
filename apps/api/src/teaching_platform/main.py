from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings, validate_api_settings


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    validate_api_settings(get_settings())
    yield


app = FastAPI(
    title="AI Teaching Platform API",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/healthz", tags=["system"])
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "api"}


@app.get("/readyz", tags=["system"])
def readyz() -> dict[str, str]:
    validate_api_settings(get_settings())
    return {"status": "ready", "service": "api"}
