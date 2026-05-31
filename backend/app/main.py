import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.scheduler import make_scheduler


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Gated on env so tests and local uvicorn don't auto-start cron-style jobs.
    # Set SCHEDULER_ENABLED=true in Railway env to turn this on in production.
    enabled = os.environ.get("SCHEDULER_ENABLED", "false").lower() == "true"
    scheduler = None
    if enabled:
        scheduler = make_scheduler()
        scheduler.start()
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown()


app = FastAPI(title="nba_alpha_prop", version="0.0.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
