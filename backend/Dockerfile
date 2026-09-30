# syntax=docker/dockerfile:1
# Build context is the repository root (see docker-compose.yml).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# Dependencies first so code changes don't invalidate the install layer.
COPY backend/pyproject.toml backend/pyproject.toml
COPY README.md README.md
RUN mkdir -p backend/songnexus && touch backend/songnexus/__init__.py \
    && pip install --upgrade pip && pip install "./backend[llm]"

COPY backend/songnexus backend/songnexus
RUN pip install --no-deps --force-reinstall "./backend"

# The committed sample snapshot, seeds and evaluation sets ship with the image.
COPY data/samples data/samples
COPY data/seeds data/seeds
COPY evaluation evaluation

RUN useradd --create-home --uid 10001 songnexus && chown -R songnexus /app
USER songnexus

ENV SONGNEXUS_SAMPLE_SNAPSHOT_PATH=/app/data/samples/musicbrainz_snapshot.jsonl.gz \
    SONGNEXUS_SEEDS_PATH=/app/data/seeds/seed_artists.json
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')"
# Load the sample on first start (a no-op afterwards), then serve.
CMD ["sh", "-c", "songnexus bootstrap && exec uvicorn songnexus.api.app:create_app --factory --host 0.0.0.0 --port 8000"]
