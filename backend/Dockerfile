# Build context: repository root (see docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app

WORKDIR /srv/backend
COPY backend/pyproject.toml ./
RUN pip install --upgrade pip && pip install .
COPY backend/ ./
COPY data/ /srv/data/
RUN mkdir -p /srv/storage && chown -R app:app /srv

USER app
ENV GEOSPATIAL_DATA_PATH=/srv/data/geospatial LOCAL_STORAGE_PATH=/srv/storage
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
