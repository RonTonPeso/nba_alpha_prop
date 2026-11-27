import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router
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


app = FastAPI(title="nba_alpha_prop", version="0.8.0", lifespan=lifespan)

_cors_origins = os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000",
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins if o.strip()],
    allow_credentials=True,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
