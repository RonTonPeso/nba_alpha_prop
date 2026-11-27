# Build context is the repo root so migrations are included.
# Build: docker build -f backend/Dockerfile -t nba-alpha-prop-backend .
#
# python:3.14-slim has no g++ and jpype1 (via nbainjuries) often builds from
# source there. 3.12 is in the project's requires-python range and has better
# wheel coverage. g++ covers any remaining native builds; JRE covers tabula.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        g++ \
        default-jre-headless \
    && rm -rf /var/lib/apt/lists/*

# Install uv from the official image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Install deps first so source edits do not bust the dep cache.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy app source and migrations.
COPY backend/app ./app
COPY backend/alembic.ini ./
COPY db/migrations ./db/migrations

EXPOSE 8000

CMD ["uv", "run", "--no-dev", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
