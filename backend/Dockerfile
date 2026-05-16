# Build context is the repo root to make sure we include the db migrations
# Build with this docker build -f backend/Dockerfile -t nba-alpha-prop-backend .
FROM python:3.14-slim

# Install uv from the official image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Install deps first so changes to source dont bust the dep cache.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy app source and migrations.
COPY backend/app ./app
COPY backend/alembic.ini ./
COPY db/migrations ./db/migrations

EXPOSE 8000

CMD ["uv", "run", "--no-dev", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
