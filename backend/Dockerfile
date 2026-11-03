# syntax=docker/dockerfile:1.7
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MLFLOW_DISABLE_AGENT_HINT=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.5.11

# Dependencies first for layer caching.
COPY pyproject.toml ./
RUN mkdir -p src/aegis && touch src/aegis/__init__.py \
    && uv pip install --system --no-cache ".[dev]" \
    && rm -rf src

COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY tests ./tests
RUN uv pip install --system --no-cache --no-deps --reinstall . \
    && useradd --create-home --uid 10001 aegis \
    && mkdir -p /app/artifacts/models && chown -R aegis:aegis /app
USER aegis
EXPOSE 8000 9108
CMD ["uvicorn", "aegis.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
