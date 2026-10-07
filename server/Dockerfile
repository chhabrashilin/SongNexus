# syntax=docker/dockerfile:1.7
# The SongNexus service image. Build from the repository root (it needs data/):
#   docker build -f server/Dockerfile -t songnexus-server .
# One image serves the API and runs the jobs (migrate, ingest) with other commands.

FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first, so source changes reuse the cached dependency layer.
COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY server/README.md ./
COPY server/src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
# The catalog snapshot and evaluation set ship with the image, so a catalog
# build is reproducible from the image alone.
COPY data/samples /app/data/samples
COPY data/eval /app/data/eval
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    SONGNEXUS_DATA_DIR=/app/data \
    SONGNEXUS_ENVIRONMENT=production
USER 10001
EXPOSE 8080
# Cloud Run sets PORT. Forwarded headers come from Google's front end.
# uvicorn's access log is off: it prints full URLs, including search queries.
# The service logs each request itself, without query strings.
CMD ["sh", "-c", "exec uvicorn songnexus.service.app:create_app --factory --host 0.0.0.0 --port \"${PORT:-8080}\" --proxy-headers --forwarded-allow-ips='*' --no-server-header --no-access-log"]
